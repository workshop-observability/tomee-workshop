package de.demo.mes.fileprocessing;

import java.io.BufferedInputStream;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.ServerSocket;
import java.net.Socket;
import java.net.SocketTimeoutException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.List;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.logging.Level;
import java.util.logging.Logger;

import de.demo.mes.infra.MBeans;
import de.demo.mes.infra.Umgebung;
import de.demo.mes.monitoring.ExecutorStatistik;
import de.demo.mes.monitoring.Fehlerzaehler;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import jakarta.ejb.ConcurrencyManagement;
import jakarta.ejb.ConcurrencyManagementType;
import jakarta.ejb.EJB;
import jakarta.ejb.Singleton;
import jakarta.ejb.Startup;

/**
 * TCP-Server des FileProcessing. Protokoll (zeilenbasiert):
 * <pre>
 *   PING                                → PONG
 *   DATEI &lt;name&gt; &lt;bytes&gt; &lt;station&gt;  → danach &lt;bytes&gt; Nutzdaten → OK &lt;zeilen&gt;
 *   ENDE                                → Verbindung wird geschlossen
 * </pre>
 * Jede Verbindung belegt für ihre gesamte Lebensdauer einen Thread aus dem
 * SocketHandler-Pool (tomee.xml: Core = Max = 250, Queue = 1000).
 */
@Singleton
@Startup
@ConcurrencyManagement(ConcurrencyManagementType.BEAN)
public class SocketServer {

    private static final Logger LOG = Logger.getLogger(SocketServer.class.getName());

    @EJB
    private DateiInhaltVerarbeitung verarbeitung;

    private final List<Lauscher> lauscher = new ArrayList<>();
    private Path eingang;
    private int leseTimeoutMs;

    @PostConstruct
    void starten() {
        String ports = Umgebung.text("MES_SOCKET_PORTS", "");
        if (ports.isEmpty()) {
            return;
        }
        eingang = Path.of(Umgebung.text("MES_DATA_DIR", "/mnt/mes_data/eingang"));
        leseTimeoutMs = Umgebung.zahl("MES_SOCKET_TIMEOUT_MS", 0);
        String[] bereich = ports.split("-");
        int von = Integer.parseInt(bereich[0]);
        int bis = bereich.length > 1 ? Integer.parseInt(bereich[1]) : von;
        try {
            Files.createDirectories(eingang);
            for (int port = von; port <= bis; port++) {
                Lauscher l = new Lauscher(new ServerSocket(port, 200));
                lauscher.add(l);
                MBeans.registrieren(l, "type=SocketServer,port=" + port);
                Thread t = new Thread(l, "socket-accept-" + port);
                t.setDaemon(true);
                t.start();
            }
            LOG.info("Socket-Server lauscht auf " + ports + ", Lese-Timeout " + leseTimeoutMs + " ms (0 = unbegrenzt)");
        } catch (IOException e) {
            LOG.log(Level.SEVERE, "Socket-Server konnte nicht starten", e);
        }
    }

    @PreDestroy
    void stoppen() {
        lauscher.forEach(Lauscher::schliessen);
    }

    private final class Lauscher implements SocketServerMXBean, Runnable {

        private final ServerSocket server;
        private final Set<Socket> offen = ConcurrentHashMap.newKeySet();
        private final AtomicInteger wartend = new AtomicInteger();
        private final AtomicLong angenommen = new AtomicLong();
        private final AtomicLong abgelehnt = new AtomicLong();
        private final AtomicLong dateien = new AtomicLong();
        private final AtomicLong bytes = new AtomicLong();
        private final AtomicLong fehler = new AtomicLong();

        Lauscher(ServerSocket server) {
            this.server = server;
        }

        @Override
        public void run() {
            ExecutorStatistik handler = ExecutorStatistik.fuer("SocketHandler");
            while (!server.isClosed()) {
                try {
                    Socket socket = server.accept();
                    angenommen.incrementAndGet();
                    offen.add(socket);
                    wartend.incrementAndGet();
                    boolean eingereicht = handler.einreichen(() -> {
                        wartend.decrementAndGet();
                        bearbeiten(socket);
                    });
                    if (!eingereicht) {
                        wartend.decrementAndGet();
                        abgelehnt.incrementAndGet();
                        Fehlerzaehler.INSTANZ.zaehlen(new RejectedExecutionException("SocketHandler voll"));
                        schliessen(socket);
                    }
                } catch (IOException e) {
                    if (!server.isClosed()) {
                        LOG.log(Level.WARNING, "accept fehlgeschlagen", e);
                        Umgebung.schlafen(100);
                    }
                }
            }
        }

        private void bearbeiten(Socket socket) {
            try (socket;
                 InputStream in = new BufferedInputStream(socket.getInputStream());
                 OutputStream out = socket.getOutputStream()) {
                socket.setSoTimeout(leseTimeoutMs);
                String zeile;
                while ((zeile = zeileLesen(in)) != null) {
                    String[] teile = zeile.trim().split("\\s+");
                    switch (teile[0]) {
                        case "PING" -> antworten(out, "PONG");
                        case "DATEI" -> antworten(out, dateiEmpfangen(in, teile));
                        case "ENDE" -> {
                            return;
                        }
                        default -> antworten(out, "FEHLER unbekanntes Kommando");
                    }
                }
            } catch (SocketTimeoutException e) {
                LOG.fine("Lese-Timeout, Verbindung geschlossen");
            } catch (IOException e) {
                LOG.log(Level.FINE, "Verbindung abgebrochen", e);
            } finally {
                offen.remove(socket);
            }
        }

        private String dateiEmpfangen(InputStream in, String[] teile) throws IOException {
            if (teile.length < 3) {
                return "FEHLER DATEI <name> <bytes> [station]";
            }
            int laenge = Integer.parseInt(teile[2]);
            byte[] inhalt = in.readNBytes(laenge);
            bytes.addAndGet(inhalt.length);
            Path datei = eingang.resolve(Path.of(teile[1]).getFileName() + "-" + System.nanoTime());
            Files.write(datei, inhalt);
            try {
                int zeilen = verarbeitung.verarbeiten(datei, teile.length > 3 ? teile[3] : "SOCKET");
                dateien.incrementAndGet();
                return "OK " + zeilen;
            } catch (Exception e) {
                fehler.incrementAndGet();
                return "FEHLER " + Fehlerzaehler.INSTANZ.zaehlen(e);
            } finally {
                Files.deleteIfExists(datei);
            }
        }

        private void antworten(OutputStream out, String text) throws IOException {
            out.write((text + "\n").getBytes(StandardCharsets.UTF_8));
            out.flush();
        }

        private String zeileLesen(InputStream in) throws IOException {
            ByteArrayOutputStream puffer = new ByteArrayOutputStream(64);
            int b;
            while ((b = in.read()) != -1 && b != '\n') {
                puffer.write(b);
            }
            return b == -1 && puffer.size() == 0 ? null : puffer.toString(StandardCharsets.UTF_8);
        }

        void schliessen() {
            try {
                server.close();
            } catch (IOException ignoriert) {
                // Shutdown
            }
            offen.forEach(this::schliessen);
        }

        private void schliessen(Socket socket) {
            try {
                socket.close();
            } catch (IOException ignoriert) {
                // bereits zu
            }
            offen.remove(socket);
        }

        @Override
        public int getPort() {
            return server.getLocalPort();
        }

        @Override
        public int getOffeneVerbindungen() {
            return offen.size();
        }

        @Override
        public long getAngenommen() {
            return angenommen.get();
        }

        @Override
        public long getAbgelehnt() {
            return abgelehnt.get();
        }

        @Override
        public int getWartendeVerbindungen() {
            return wartend.get();
        }

        @Override
        public long getDateien() {
            return dateien.get();
        }

        @Override
        public long getBytes() {
            return bytes.get();
        }

        @Override
        public long getVerarbeitungsFehler() {
            return fehler.get();
        }
    }
}
