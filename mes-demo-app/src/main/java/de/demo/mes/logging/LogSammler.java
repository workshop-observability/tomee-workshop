package de.demo.mes.logging;

import java.io.BufferedWriter;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.time.Instant;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;
import java.util.logging.Logger;

import de.demo.mes.infra.MBeans;
import de.demo.mes.monitoring.LogSammlerMXBean;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import jakarta.ejb.ConcurrencyManagement;
import jakarta.ejb.ConcurrencyManagementType;
import jakarta.ejb.Singleton;
import jakarta.ejb.Startup;

/**
 * Nachbildung des Log-Wegs beim Kunden: Das MES-Framework schickt Logeinträge per HTTP,
 * ein Singleton legt sie in eine Queue, ein eigener Thread schreibt einmal pro Sekunde
 * in eine Textdatei (von dort holt sie ein Agent nach Elasticsearch).
 *
 * <p>Wie sich das bei einer Log-Flut verhält, entscheidet allein die Queue:
 * <ul>
 * <li>{@code unbegrenzt} – nimmt alles an, der Rückstand wächst im Heap (vermutlich Kundenstand)</li>
 * <li>{@code verwerfen} – begrenzt, bei voller Queue geht der Eintrag verloren und wird gezählt</li>
 * <li>{@code blockieren} – begrenzt, der Aufrufer wartet auf einen Platz und hält so lange seinen HTTP-Thread</li>
 * </ul>
 */
@Singleton
@Startup
@ConcurrencyManagement(ConcurrencyManagementType.BEAN)
public class LogSammler {

    public static final List<String> MODI = List.of("unbegrenzt", "verwerfen", "blockieren");

    private static final Logger LOG = Logger.getLogger(LogSammler.class.getName());
    private static final long MAX_DATEI_BYTES = 20L * 1024 * 1024;

    private record Eintrag(long zeitMs, String station, String text) {
    }

    private final LinkedBlockingQueue<Eintrag> queue = new LinkedBlockingQueue<>();
    private final Object platz = new Object();
    private final Statistik statistik = new Statistik();
    private final AtomicInteger wartend = new AtomicInteger();
    private final AtomicLong angenommen = new AtomicLong();
    private final AtomicLong geschrieben = new AtomicLong();
    private final AtomicLong verworfen = new AtomicLong();

    private volatile String modus = "unbegrenzt";
    private volatile int kapazitaet = 10_000;
    private volatile int schreibLimit;
    private volatile long letzteSchreibdauerMs;
    private volatile boolean laeuft = true;
    private Thread schreiber;
    private Path datei;

    @PostConstruct
    void starten() {
        datei = Path.of(System.getProperty("catalina.base", System.getProperty("java.io.tmpdir")), "logs",
                "mes-protokoll.log");
        MBeans.registrieren(statistik, "type=LogSammler");
        schreiber = new Thread(this::schreiben, "mes-log-schreiber");
        schreiber.setDaemon(true);
        schreiber.start();
    }

    @PreDestroy
    void stoppen() {
        laeuft = false;
        schreiber.interrupt();
        synchronized (platz) {
            platz.notifyAll();
        }
    }

    /** @return false, wenn der Eintrag verworfen wurde */
    public boolean aufnehmen(String station, String text) {
        Eintrag eintrag = new Eintrag(System.currentTimeMillis(), station, text == null ? "" : text);
        switch (modus) {
            case "verwerfen" -> {
                if (queue.size() >= kapazitaet) {
                    verworfen.incrementAndGet();
                    return false;
                }
            }
            case "blockieren" -> {
                if (!aufPlatzWarten()) {
                    verworfen.incrementAndGet();
                    return false;
                }
            }
            default -> {
                // unbegrenzt: alles annehmen
            }
        }
        queue.add(eintrag);
        angenommen.incrementAndGet();
        return true;
    }

    private boolean aufPlatzWarten() {
        if (queue.size() < kapazitaet) {
            return true;
        }
        wartend.incrementAndGet();
        try {
            synchronized (platz) {
                while (laeuft && "blockieren".equals(modus) && queue.size() >= kapazitaet) {
                    platz.wait(1000);
                }
            }
            return true;
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            return false;
        } finally {
            wartend.decrementAndGet();
        }
    }

    /**
     * @param schreibLimit Zeilen pro Sekunde, die der Schreiber schafft (0 = ohne Grenze) –
     *                     simuliert eine langsame Platte oder einen gebremsten Log-Agenten
     */
    public Map<String, Object> konfigurieren(String modus, int kapazitaet, int schreibLimit) {
        String neu = modus.toLowerCase(Locale.ROOT);
        if (!MODI.contains(neu)) {
            throw new IllegalArgumentException("Modus muss einer von " + MODI + " sein");
        }
        this.modus = neu;
        this.kapazitaet = Math.max(1, kapazitaet);
        this.schreibLimit = Math.max(0, schreibLimit);
        synchronized (platz) {
            platz.notifyAll();
        }
        LOG.info("Log-Sammler: Modus " + neu + ", Kapazität " + this.kapazitaet + ", Schreiblimit "
                + (this.schreibLimit == 0 ? "keins" : this.schreibLimit + " Zeilen/s"));
        return zustand();
    }

    /** Zurück auf den Normalzustand; der Rückstand wird verworfen. */
    public Map<String, Object> zuruecksetzen() {
        int rueckstand = queue.size();
        queue.clear();
        konfigurieren("unbegrenzt", 10_000, 0);
        Map<String, Object> m = zustand();
        m.put("verworfenerRueckstand", rueckstand);
        return m;
    }

    public Map<String, Object> zustand() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("modus", modus);
        m.put("queue", queue.size());
        m.put("kapazitaet", statistik.getQueueKapazitaet());
        m.put("schreibLimitProSekunde", schreibLimit);
        m.put("aeltesterEintragSekunden", Math.round(statistik.getAeltesterEintragSekunden() * 10) / 10.0);
        m.put("wartendeAufrufer", wartend.get());
        m.put("angenommen", angenommen.get());
        m.put("geschrieben", geschrieben.get());
        m.put("verworfen", verworfen.get());
        return m;
    }

    /** Einmal pro Sekunde alles (bzw. höchstens schreibLimit Zeilen) in die Datei. */
    private void schreiben() {
        while (laeuft) {
            try {
                Thread.sleep(1000);
            } catch (InterruptedException e) {
                if (!laeuft) {
                    return;
                }
            }
            int limit = schreibLimit > 0 ? schreibLimit : Integer.MAX_VALUE;
            List<Eintrag> stapel = new ArrayList<>(Math.min(limit, Math.max(16, queue.size())));
            queue.drainTo(stapel, limit);
            if (stapel.isEmpty()) {
                continue;
            }
            long start = System.currentTimeMillis();
            try {
                rotieren();
                try (BufferedWriter w = Files.newBufferedWriter(datei, StandardCharsets.UTF_8,
                        StandardOpenOption.CREATE, StandardOpenOption.APPEND)) {
                    for (Eintrag e : stapel) {
                        w.write(Instant.ofEpochMilli(e.zeitMs()) + " " + e.station() + " " + e.text());
                        w.newLine();
                    }
                }
                geschrieben.addAndGet(stapel.size());
            } catch (IOException e) {
                LOG.warning("Log-Sammler kann nicht schreiben: " + e);
            } finally {
                letzteSchreibdauerMs = System.currentTimeMillis() - start;
                synchronized (platz) {
                    platz.notifyAll();
                }
            }
        }
    }

    private void rotieren() throws IOException {
        if (Files.exists(datei) && Files.size(datei) > MAX_DATEI_BYTES) {
            Files.move(datei, datei.resolveSibling("mes-protokoll.log.1"), StandardCopyOption.REPLACE_EXISTING);
        }
    }

    private final class Statistik implements LogSammlerMXBean {

        @Override
        public String getModus() {
            return modus;
        }

        @Override
        public int getQueueTiefe() {
            return queue.size();
        }

        @Override
        public int getQueueKapazitaet() {
            return "unbegrenzt".equals(modus) ? -1 : kapazitaet;
        }

        @Override
        public double getAeltesterEintragSekunden() {
            Eintrag kopf = queue.peek();
            return kopf == null ? 0 : (System.currentTimeMillis() - kopf.zeitMs()) / 1000.0;
        }

        @Override
        public int getWartendeAufrufer() {
            return wartend.get();
        }

        @Override
        public int getSchreibLimitProSekunde() {
            return schreibLimit;
        }

        @Override
        public long getAngenommen() {
            return angenommen.get();
        }

        @Override
        public long getGeschrieben() {
            return geschrieben.get();
        }

        @Override
        public long getVerworfen() {
            return verworfen.get();
        }

        @Override
        public long getLetzteSchreibdauerMs() {
            return letzteSchreibdauerMs;
        }
    }
}
