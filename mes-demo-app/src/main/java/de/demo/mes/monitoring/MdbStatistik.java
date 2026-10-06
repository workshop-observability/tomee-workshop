package de.demo.mes.monitoring;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicLong;

import de.demo.mes.infra.MBeans;

public final class MdbStatistik implements MdbStatistikMXBean {

    private static final Map<String, MdbStatistik> ALLE = new ConcurrentHashMap<>();
    private static final long FENSTER_MS = 60_000;

    private final String mdb;
    private final AtomicInteger aktiv = new AtomicInteger();
    private final AtomicLong verarbeitet = new AtomicLong();
    private final AtomicLong fehler = new AtomicLong();
    private final AtomicLong wiederholungen = new AtomicLong();
    private final AtomicLong letzteLaufzeitMs = new AtomicLong();
    private volatile long letzteWartezeitMs;
    private volatile long fensterMax;
    private volatile long fensterStart = System.currentTimeMillis();
    private volatile long vorigesFensterMax;

    private MdbStatistik(String mdb) {
        this.mdb = mdb;
    }

    public static MdbStatistik fuer(String mdb) {
        return ALLE.computeIfAbsent(mdb, name -> {
            MdbStatistik neu = new MdbStatistik(name);
            MBeans.registrieren(neu, "type=Mdb,name=" + name);
            return neu;
        });
    }

    public static Map<String, MdbStatistik> alle() {
        return ALLE;
    }

    /**
     * @param gesendetMs JMSTimestamp der Nachricht (0 = unbekannt)
     * @return Startzeitpunkt für {@link #beendet(long, boolean)}
     */
    public long begonnen(long gesendetMs, boolean wiederholt) {
        long jetzt = System.currentTimeMillis();
        aktiv.incrementAndGet();
        if (wiederholt) {
            wiederholungen.incrementAndGet();
        }
        if (gesendetMs > 0) {
            merkeWartezeit(Math.max(0, jetzt - gesendetMs));
        }
        return jetzt;
    }

    public void beendet(long startMs, boolean erfolgreich) {
        aktiv.decrementAndGet();
        letzteLaufzeitMs.set(System.currentTimeMillis() - startMs);
        if (erfolgreich) {
            verarbeitet.incrementAndGet();
        } else {
            fehler.incrementAndGet();
        }
    }

    private synchronized void merkeWartezeit(long ms) {
        long jetzt = System.currentTimeMillis();
        if (jetzt - fensterStart > FENSTER_MS) {
            vorigesFensterMax = fensterMax;
            fensterMax = 0;
            fensterStart = jetzt;
        }
        fensterMax = Math.max(fensterMax, ms);
        letzteWartezeitMs = ms;
    }

    @Override
    public String getMdb() {
        return mdb;
    }

    @Override
    public int getAktiv() {
        return aktiv.get();
    }

    @Override
    public long getVerarbeitet() {
        return verarbeitet.get();
    }

    @Override
    public long getFehler() {
        return fehler.get();
    }

    @Override
    public long getWiederholungen() {
        return wiederholungen.get();
    }

    @Override
    public double getLetzteWartezeitSekunden() {
        return letzteWartezeitMs / 1000.0;
    }

    @Override
    public double getMaxWartezeitSekunden() {
        boolean abgelaufen = System.currentTimeMillis() - fensterStart > FENSTER_MS;
        return (abgelaufen ? 0 : Math.max(fensterMax, vorigesFensterMax)) / 1000.0;
    }

    @Override
    public long getLetzteLaufzeitMs() {
        return letzteLaufzeitMs.get();
    }
}
