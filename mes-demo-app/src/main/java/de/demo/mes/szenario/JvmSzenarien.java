package de.demo.mes.szenario;

import java.io.IOException;
import java.io.RandomAccessFile;
import java.nio.ByteBuffer;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.atomic.AtomicInteger;

import de.demo.mes.infra.Umgebung;
import de.demo.mes.monitoring.SzenarioStatus;
import jakarta.enterprise.context.ApplicationScoped;

/**
 * JVM- und Container-Störungen: Heap-Leck (Facade S09, GC-Spirale S19), File Descriptors (S10),
 * Speicher außerhalb des Heaps (S14) und kurzlebiger Müll als GC-Last (S19).
 */
@ApplicationScoped
public class JvmSzenarien {

    private static final int MB = 1024 * 1024;

    private final List<byte[]> leck = new CopyOnWriteArrayList<>();
    private final List<RandomAccessFile> dateien = new CopyOnWriteArrayList<>();
    private final List<ByteBuffer> offHeap = new CopyOnWriteArrayList<>();
    private final List<Thread> threads = new CopyOnWriteArrayList<>();
    private final AtomicInteger threadNummer = new AtomicInteger();

    /** Heap-Leck: bleibt bis {@link #leckFreigeben()} bestehen. */
    public Map<String, Object> leck(int mb) {
        try {
            leck.addAll(belegen(mb));
            SzenarioStatus.INSTANZ.heapMb.addAndGet(mb);
            return Map.of("leckGesamtMb", leck.size());
        } catch (OutOfMemoryError e) {
            return Map.of("leckGesamtMb", leck.size(), "fehler", "OutOfMemoryError: " + e.getMessage());
        }
    }

    public long leckFreigeben() {
        long mb = leck.size();
        leck.clear();
        SzenarioStatus.INSTANZ.heapMb.addAndGet(-mb);
        return mb;
    }

    /** Öffnet Dateien und schließt sie nicht – jede belegt einen File Descriptor. */
    public int dateienOeffnen(int anzahl) throws IOException {
        Path verzeichnis = Files.createDirectories(Path.of(System.getProperty("java.io.tmpdir"), "mes-fd-leck"));
        for (int i = 0; i < anzahl; i++) {
            Path datei = verzeichnis.resolve("datei-" + (dateien.size() % 50));
            dateien.add(new RandomAccessFile(datei.toFile(), "rw"));
            SzenarioStatus.INSTANZ.dateien.incrementAndGet();
        }
        return dateien.size();
    }

    public int dateienSchliessen() {
        int anzahl = 0;
        for (RandomAccessFile f : dateien) {
            try {
                f.close();
                anzahl++;
            } catch (IOException ignoriert) {
                // weiter mit der nächsten
            }
            dateien.remove(f);
            SzenarioStatus.INSTANZ.dateien.decrementAndGet();
        }
        return anzahl;
    }

    /**
     * Direct Buffer: Speicher außerhalb des Heaps. JMX sieht ihn (BufferPool „direct“), -Xmx nicht –
     * er zählt aber gegen das Container-Limit.
     */
    public Map<String, Object> offHeap(int mb) {
        String fehler = null;
        try {
            for (int i = 0; i < mb; i++) {
                ByteBuffer puffer = ByteBuffer.allocateDirect(MB);
                for (int j = 0; j < MB; j += 4096) {
                    puffer.put(j, (byte) 1);
                }
                offHeap.add(puffer);
                SzenarioStatus.INSTANZ.offHeapMb.incrementAndGet();
            }
        } catch (OutOfMemoryError e) {
            fehler = "OutOfMemoryError: " + e.getMessage();
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("offHeapGesamtMb", offHeap.size());
        if (fehler != null) {
            m.put("fehler", fehler);
        }
        return m;
    }

    public long offHeapFreigeben() {
        long mb = offHeap.size();
        offHeap.clear();
        SzenarioStatus.INSTANZ.offHeapMb.addAndGet(-mb);
        // Direct Buffer werden erst freigegeben, wenn der GC ihre Hüllen einsammelt
        System.gc();
        return mb;
    }

    /**
     * Startet schlafende Threads, die ihren Stack bis etwa {@code stackKb} belegen. Jeder Thread
     * kostet Speicher außerhalb des Heaps – sichtbar nur von außen (Container, NMT), nicht in JMX.
     */
    public Map<String, Object> threadsStarten(int anzahl, int stackKb, int sekunden) {
        int tiefe = Math.max(1, stackKb * 1024 / RAHMEN_BYTES);
        int gestartet = 0;
        String fehler = null;
        try {
            for (int i = 0; i < anzahl; i++) {
                Thread t = new Thread(() -> {
                    SzenarioStatus.INSTANZ.threads.incrementAndGet();
                    try {
                        stapeln(tiefe, sekunden * 1000L);
                    } finally {
                        SzenarioStatus.INSTANZ.threads.decrementAndGet();
                        threads.remove(Thread.currentThread());
                    }
                }, "mes-zusatz-" + threadNummer.incrementAndGet());
                t.setDaemon(true);
                t.start();
                threads.add(t);
                gestartet++;
            }
        } catch (OutOfMemoryError e) {
            // "unable to create native thread": Prozess- oder Speichergrenze erreicht
            fehler = "OutOfMemoryError: " + e.getMessage();
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("gestartet", gestartet);
        m.put("zusaetzlicheThreads", threads.size());
        m.put("stapeltiefe", tiefe);
        if (fehler != null) {
            m.put("fehler", fehler);
        }
        return m;
    }

    public int threadsBeenden() {
        int anzahl = threads.size();
        threads.forEach(Thread::interrupt);
        return anzahl;
    }

    /** Ungefähre Größe eines Stack-Rahmens von {@link #stapeln(int, long)} in Bytes. */
    private static final int RAHMEN_BYTES = 128;

    /** Jede Ebene legt einen Stack-Rahmen an; ganz unten schläft der Thread, der Stack bleibt belegt. */
    private static long stapeln(int rest, long ms) {
        long a = rest;
        long b = a * 31;
        long c = b ^ a;
        long d = c + 7;
        long e = d * 11;
        long f = e - a;
        long g = f + b;
        long h = g ^ c;
        if (rest > 0) {
            return stapeln(rest - 1, ms) + ((a + b + c + d + e + f + g + h) & 1);
        }
        Umgebung.schlafen(ms);
        return h;
    }

    /**
     * Kurzlebiger Müll: belegt {@code kb} und gibt ihn mit dem Ende des Requests wieder frei.
     * Harmlos, solange der Heap Luft hat – bei vollem Heap treibt er die Garbage Collection an.
     */
    public int muell(int kb) {
        int bloecke = Math.max(1, kb / 64);
        for (int i = 0; i < bloecke; i++) {
            byte[] block = new byte[64 * 1024];
            block[i % block.length] = (byte) i;
            senke = block[block.length - 1];
        }
        return bloecke;
    }

    /** Verhindert, dass der JIT-Compiler die Allokationen in {@link #muell(int)} wegoptimiert. */
    @SuppressWarnings("unused")
    private static volatile byte senke;

    public Map<String, Object> zuruecksetzen() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("heapLeckMb", leckFreigeben());
        m.put("dateien", dateienSchliessen());
        m.put("offHeapMb", offHeapFreigeben());
        m.put("threads", threadsBeenden());
        return m;
    }

    private static List<byte[]> belegen(int mb) {
        List<byte[]> bloecke = new ArrayList<>(mb);
        for (int i = 0; i < mb; i++) {
            byte[] block = new byte[MB];
            // Seiten tatsächlich anfassen, damit der RSS wirklich wächst
            for (int j = 0; j < block.length; j += 4096) {
                block[j] = 1;
            }
            bloecke.add(block);
        }
        return bloecke;
    }
}
