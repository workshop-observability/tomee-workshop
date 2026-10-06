package de.demo.mes.monitoring;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;
import java.util.logging.Logger;

import de.demo.mes.infra.Umgebung;
import jakarta.transaction.Status;

public final class Transaktionen implements TransaktionenMXBean {

    public static final Transaktionen INSTANZ = new Transaktionen();

    private static final Logger LOG = Logger.getLogger(Transaktionen.class.getName());

    private record Eintrag(String wo, long startMs, Thread thread) {
    }

    private final Map<Long, Eintrag> aktiv = new ConcurrentHashMap<>();
    private final Map<Long, Long> zuletztGewarnt = new ConcurrentHashMap<>();
    private final AtomicLong naechsteId = new AtomicLong();
    private final AtomicLong commits = new AtomicLong();
    private final AtomicLong rollbacks = new AtomicLong();
    private final long warnSchwelleSekunden = Umgebung.zahl("TX_WARN_SEKUNDEN", 60);

    private Transaktionen() {
    }

    public long begonnen(String wo) {
        long id = naechsteId.incrementAndGet();
        aktiv.put(id, new Eintrag(wo, System.currentTimeMillis(), Thread.currentThread()));
        return id;
    }

    public void beendet(long id, int jtaStatus) {
        Eintrag e = aktiv.remove(id);
        zuletztGewarnt.remove(id);
        if (jtaStatus == Status.STATUS_COMMITTED) {
            commits.incrementAndGet();
        } else {
            rollbacks.incrementAndGet();
            if (e != null) {
                LOG.warning(() -> String.format("Transaktion zurückgerollt nach %d s: %s",
                        (System.currentTimeMillis() - e.startMs()) / 1000, e.wo()));
            }
        }
    }

    /** Vom Überwachungs-Thread aufgerufen: loggt lange Transaktionen höchstens einmal pro Minute. */
    public void langeTransaktionenLoggen() {
        long jetzt = System.currentTimeMillis();
        aktiv.forEach((id, e) -> {
            long alter = (jetzt - e.startMs()) / 1000;
            if (alter < warnSchwelleSekunden) {
                return;
            }
            Long gewarnt = zuletztGewarnt.get(id);
            if (gewarnt == null || jetzt - gewarnt > 60_000) {
                zuletztGewarnt.put(id, jetzt);
                LOG.warning(String.format("Transaktion läuft seit %d s (Schwelle %d s): %s, Thread %s, Zustand %s",
                        alter, warnSchwelleSekunden, e.wo(), e.thread().getName(), e.thread().getState()));
            }
        });
    }

    public List<Map<String, Object>> liste() {
        long jetzt = System.currentTimeMillis();
        List<Map<String, Object>> ergebnis = new ArrayList<>();
        aktiv.values().stream()
                .sorted((a, b) -> Long.compare(a.startMs(), b.startMs()))
                .limit(20)
                .forEach(e -> {
                    Map<String, Object> m = new LinkedHashMap<>();
                    m.put("wo", e.wo());
                    m.put("sekunden", (jetzt - e.startMs()) / 1000);
                    m.put("thread", e.thread().getName());
                    m.put("zustand", e.thread().getState().name());
                    ergebnis.add(m);
                });
        return ergebnis;
    }

    @Override
    public int getAktive() {
        return aktiv.size();
    }

    @Override
    public double getAeltesteSekunden() {
        long jetzt = System.currentTimeMillis();
        return aktiv.values().stream().mapToLong(e -> jetzt - e.startMs()).max().orElse(0) / 1000.0;
    }

    @Override
    public int getUeberSchwelle() {
        long grenze = System.currentTimeMillis() - warnSchwelleSekunden * 1000;
        return (int) aktiv.values().stream().filter(e -> e.startMs() < grenze).count();
    }

    @Override
    public long getWarnSchwelleSekunden() {
        return warnSchwelleSekunden;
    }

    @Override
    public long getCommits() {
        return commits.get();
    }

    @Override
    public long getRollbacks() {
        return rollbacks.get();
    }
}
