package de.demo.mes.monitoring;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

import de.demo.mes.infra.MBeans;

public final class SchedulerJob implements SchedulerJobMXBean {

    private static final Map<String, SchedulerJob> JOBS = new ConcurrentHashMap<>();

    private final String scheduler;
    private final String job;
    private volatile long sollIntervallSekunden;
    private final long erzeugtMs = System.currentTimeMillis();

    private final AtomicLong letzterStartMs = new AtomicLong();
    private final AtomicLong letzteVerspaetungMs = new AtomicLong();
    private final AtomicLong maxVerspaetungMs = new AtomicLong();
    private final AtomicLong laeufe = new AtomicLong();
    private final AtomicLong fehler = new AtomicLong();
    private final AtomicLong misfires = new AtomicLong();
    private final AtomicLong uebersprungen = new AtomicLong();
    private final AtomicLong letzteLaufzeitMs = new AtomicLong();
    private final AtomicInteger laeuftGerade = new AtomicInteger();
    private final AtomicInteger wartend = new AtomicInteger();

    private SchedulerJob(String scheduler, String job, long sollIntervallSekunden) {
        this.scheduler = scheduler;
        this.job = job;
        this.sollIntervallSekunden = sollIntervallSekunden;
    }

    /** Liefert (und registriert beim ersten Aufruf) die Statistik eines Jobs. */
    public static SchedulerJob fuer(String scheduler, String job, long sollIntervallSekunden) {
        return JOBS.computeIfAbsent(scheduler + "/" + job, k -> {
            SchedulerJob neu = new SchedulerJob(scheduler, job, sollIntervallSekunden);
            MBeans.registrieren(neu, "type=SchedulerJob,scheduler=" + scheduler + ",job=" + job);
            return neu;
        });
    }

    public static Map<String, SchedulerJob> alle() {
        return JOBS;
    }

    /**
     * Beginn eines Laufs.
     *
     * @param geplantMs geplanter Startzeitpunkt, oder 0 – dann wird die Verspätung
     *                  aus dem Abstand zum vorherigen Lauf abgeleitet
     * @return Startzeitpunkt für {@link #beendet(long, boolean)}
     */
    public long gestartet(long geplantMs) {
        long jetzt = System.currentTimeMillis();
        long vorher = letzterStartMs.getAndSet(jetzt);
        long verspaetung;
        if (geplantMs > 0) {
            verspaetung = jetzt - geplantMs;
        } else if (vorher > 0) {
            verspaetung = (jetzt - vorher) - sollIntervallSekunden * 1000;
        } else {
            verspaetung = 0;
        }
        verspaetung = Math.max(0, verspaetung);
        letzteVerspaetungMs.set(verspaetung);
        maxVerspaetungMs.accumulateAndGet(verspaetung, Math::max);
        laeuftGerade.incrementAndGet();
        return jetzt;
    }

    public void beendet(long startMs, boolean erfolgreich) {
        laeuftGerade.decrementAndGet();
        letzteLaufzeitMs.set(System.currentTimeMillis() - startMs);
        laeufe.incrementAndGet();
        if (!erfolgreich) {
            fehler.incrementAndGet();
        }
    }

    public void misfire() {
        misfires.incrementAndGet();
    }

    /** Lauf gescheitert, bevor er beginnen konnte (z. B. Sperre des Singletons nicht bekommen). */
    public void fehlgeschlagen() {
        fehler.incrementAndGet();
    }

    /** Zählt Aufrufe, die auf eine Sperre warten und dabei einen Scheduler-Thread belegen. */
    public AtomicInteger wartend() {
        return wartend;
    }

    /** Termin fällig, aber nicht ausgeführt, weil der vorige Lauf noch lief (Überlappungsschutz). */
    public void uebersprungen() {
        uebersprungen.incrementAndGet();
    }

    public void setSollIntervallSekunden(long sekunden) {
        sollIntervallSekunden = sekunden;
    }

    @Override
    public String getScheduler() {
        return scheduler;
    }

    @Override
    public String getJob() {
        return job;
    }

    @Override
    public long getSollIntervallSekunden() {
        return sollIntervallSekunden;
    }

    @Override
    public long getLetzterStartEpochSekunden() {
        return letzterStartMs.get() / 1000;
    }

    @Override
    public double getSekundenSeitLetztemStart() {
        long basis = letzterStartMs.get() > 0 ? letzterStartMs.get() : erzeugtMs;
        return (System.currentTimeMillis() - basis) / 1000.0;
    }

    @Override
    public long getLetzteVerspaetungMs() {
        return letzteVerspaetungMs.get();
    }

    @Override
    public long getMaxVerspaetungMs() {
        return maxVerspaetungMs.get();
    }

    @Override
    public long getLaeufe() {
        return laeufe.get();
    }

    @Override
    public long getFehler() {
        return fehler.get();
    }

    @Override
    public long getMisfires() {
        return misfires.get();
    }

    @Override
    public long getUebersprungen() {
        return uebersprungen.get();
    }

    @Override
    public long getLetzteLaufzeitMs() {
        return letzteLaufzeitMs.get();
    }

    @Override
    public int getLaeuftGerade() {
        return laeuftGerade.get();
    }

    @Override
    public int getWartend() {
        return wartend.get();
    }

    @Override
    public void zuruecksetzen() {
        maxVerspaetungMs.set(0);
        misfires.set(0);
        fehler.set(0);
        uebersprungen.set(0);
    }
}
