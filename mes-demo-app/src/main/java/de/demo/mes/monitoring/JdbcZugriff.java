package de.demo.mes.monitoring;

import java.lang.reflect.InvocationHandler;
import java.lang.reflect.InvocationTargetException;
import java.lang.reflect.Proxy;
import java.sql.Connection;
import java.sql.SQLException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.AtomicLong;

import javax.sql.DataSource;

import de.demo.mes.infra.MBeans;

/**
 * Misst jede Ausleihe aus einem DataSource-Pool. Die Connection wird in einen
 * Proxy verpackt, damit auch das Zurückgeben (close) erfasst wird.
 */
public final class JdbcZugriff implements JdbcZugriffMXBean {

    private static final Map<String, JdbcZugriff> ALLE = new ConcurrentHashMap<>();
    private static final long FENSTER_MS = 60_000;

    private record Ausleihe(long startMs, String thread, String aktion) {
    }

    private final String dataSource;
    private final Map<Object, Ausleihe> ausgeliehen = new ConcurrentHashMap<>();
    private final Map<Thread, Long> wartend = new ConcurrentHashMap<>();
    private final AtomicLong ausleihen = new AtomicLong();
    private final AtomicLong fehler = new AtomicLong();
    private final AtomicLong wartezeitSumme = new AtomicLong();
    private final AtomicLong letzteWartezeit = new AtomicLong();
    private volatile long fensterMax;
    private volatile long fensterStart = System.currentTimeMillis();
    private volatile long vorigesFensterMax;

    private JdbcZugriff(String dataSource) {
        this.dataSource = dataSource;
    }

    public static JdbcZugriff fuer(String dataSource) {
        return ALLE.computeIfAbsent(dataSource, name -> {
            JdbcZugriff neu = new JdbcZugriff(name);
            MBeans.registrieren(neu, "type=JdbcZugriff,datasource=" + name);
            return neu;
        });
    }

    public static Map<String, JdbcZugriff> alle() {
        return ALLE;
    }

    public Connection holen(DataSource ds, String aktion) throws SQLException {
        Thread thread = Thread.currentThread();
        long start = System.currentTimeMillis();
        wartend.put(thread, start);
        try {
            Connection echt = ds.getConnection();
            merkeWartezeit(System.currentTimeMillis() - start);
            ausleihen.incrementAndGet();
            return verpacken(echt, aktion);
        } catch (SQLException | RuntimeException e) {
            fehler.incrementAndGet();
            merkeWartezeit(System.currentTimeMillis() - start);
            throw e;
        } finally {
            wartend.remove(thread);
        }
    }

    /** Die Connection bleibt als ausgeliehen stehen, bis close() aufgerufen wird. */
    private Connection verpacken(Connection echt, String aktion) {
        Object schluessel = new Object();
        ausgeliehen.put(schluessel,
                new Ausleihe(System.currentTimeMillis(), Thread.currentThread().getName(), aktion));
        InvocationHandler handler = (proxy, methode, args) -> {
            if ("close".equals(methode.getName())) {
                ausgeliehen.remove(schluessel);
            }
            try {
                return methode.invoke(echt, args);
            } catch (InvocationTargetException e) {
                throw e.getCause();
            }
        };
        return (Connection) Proxy.newProxyInstance(
                JdbcZugriff.class.getClassLoader(), new Class<?>[] {Connection.class}, handler);
    }

    private synchronized void merkeWartezeit(long ms) {
        long jetzt = System.currentTimeMillis();
        if (jetzt - fensterStart > FENSTER_MS) {
            vorigesFensterMax = fensterMax;
            fensterMax = 0;
            fensterStart = jetzt;
        }
        fensterMax = Math.max(fensterMax, ms);
        letzteWartezeit.set(ms);
        wartezeitSumme.addAndGet(ms);
    }

    public Map<String, Object> schnappschuss() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("dataSource", dataSource);
        m.put("wartendeThreads", getWartendeThreads());
        m.put("laengsteWartezeitSekunden", runden(getLaengsteAktuelleWartezeitSekunden()));
        m.put("ausgeliehen", getAusgelieheneConnections());
        m.put("aeltesteAusleiheSekunden", runden(getAeltesteAusleiheSekunden()));
        ausgeliehen.values().stream().min((a, b) -> Long.compare(a.startMs(), b.startMs()))
                .ifPresent(a -> m.put("aeltesteAusleihe", a.aktion() + " @ " + a.thread()));
        m.put("maxWartezeitMs60s", getMaxWartezeitMs());
        m.put("ausleihFehler", getAusleihFehler());
        return m;
    }

    private static double runden(double wert) {
        return Math.round(wert * 10) / 10.0;
    }

    @Override
    public String getDataSource() {
        return dataSource;
    }

    @Override
    public int getWartendeThreads() {
        return wartend.size();
    }

    @Override
    public int getAusgelieheneConnections() {
        return ausgeliehen.size();
    }

    @Override
    public double getAeltesteAusleiheSekunden() {
        long jetzt = System.currentTimeMillis();
        return ausgeliehen.values().stream().mapToLong(a -> jetzt - a.startMs()).max().orElse(0) / 1000.0;
    }

    @Override
    public long getAusleihen() {
        return ausleihen.get();
    }

    @Override
    public long getAusleihFehler() {
        return fehler.get();
    }

    @Override
    public long getWartezeitMsSumme() {
        return wartezeitSumme.get();
    }

    @Override
    public long getLetzteWartezeitMs() {
        return letzteWartezeit.get();
    }

    @Override
    public long getMaxWartezeitMs() {
        boolean fensterAbgelaufen = System.currentTimeMillis() - fensterStart > FENSTER_MS;
        long laufend = (long) (getLaengsteAktuelleWartezeitSekunden() * 1000);
        long gemessen = fensterAbgelaufen ? 0 : Math.max(fensterMax, vorigesFensterMax);
        return Math.max(gemessen, laufend);
    }

    @Override
    public double getLaengsteAktuelleWartezeitSekunden() {
        long jetzt = System.currentTimeMillis();
        return wartend.values().stream().mapToLong(t -> jetzt - t).max().orElse(0) / 1000.0;
    }
}
