package de.demo.mes.monitoring;

import java.sql.SQLException;
import java.sql.SQLTimeoutException;
import java.util.EnumMap;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.atomic.AtomicLong;

public final class Fehlerzaehler implements FehlerzaehlerMXBean {

    public enum Art {
        POOL_ERSCHOEPFT, BEAN_POOL_TIMEOUT, SINGLETON_TIMEOUT, SPERR_TIMEOUT,
        ABFRAGE_TIMEOUT, TRANSAKTION_ABGEBROCHEN, EXECUTOR_ABGELEHNT, CLIENT_ABBRUCH, DB_SITZUNGSLIMIT, SONSTIGE
    }

    public static final Fehlerzaehler INSTANZ = new Fehlerzaehler();

    /**
     * Oracle lehnt die Anmeldung ab: ORA-02391 (SESSIONS_PER_USER), ORA-00018 (sessions),
     * ORA-00020 (processes), ORA-12516/12519/12520 (Listener findet keinen freien Handler).
     */
    private static final Set<Integer> SITZUNGSLIMIT = Set.of(2391, 18, 20, 12516, 12519, 12520);

    private final Map<Art, AtomicLong> zaehler = new EnumMap<>(Art.class);

    private Fehlerzaehler() {
        for (Art art : Art.values()) {
            zaehler.put(art, new AtomicLong());
        }
    }

    public Art zaehlen(Throwable fehler) {
        Art art = einordnen(fehler);
        zaehler.get(art).incrementAndGet();
        return art;
    }

    /** Ordnet einen Fehler anhand der gesamten Cause-Kette ein. */
    public static Art einordnen(Throwable fehler) {
        for (Throwable t = fehler; t != null; t = t.getCause() == t ? null : t.getCause()) {
            String typ = t.getClass().getName();
            String text = String.valueOf(t.getMessage()).toLowerCase(Locale.ROOT);
            if (typ.endsWith("PoolExhaustedException") || text.contains("unable to fetch a connection")
                    || text.contains("timeout waiting for idle object")) {
                return Art.POOL_ERSCHOEPFT;
            }
            if (typ.endsWith("ConcurrentAccessTimeoutException")) {
                return text.contains("singleton") || text.contains("lock") ? Art.SINGLETON_TIMEOUT : Art.BEAN_POOL_TIMEOUT;
            }
            if (t instanceof SQLException sql) {
                int code = sql.getErrorCode();
                if (SITZUNGSLIMIT.contains(code) || text.contains("ora-02391") || text.contains("ora-00018")
                        || text.contains("ora-00020")) {
                    return Art.DB_SITZUNGSLIMIT;
                }
                if (code == 30006 || code == 54) {
                    return Art.SPERR_TIMEOUT;
                }
                if (code == 1013 || sql instanceof SQLTimeoutException || text.contains("read timed out")) {
                    return Art.ABFRAGE_TIMEOUT;
                }
            }
            if (t instanceof RejectedExecutionException) {
                return Art.EXECUTOR_ABGELEHNT;
            }
            if (typ.endsWith("ClientAbortException") || text.contains("broken pipe")
                    || text.contains("connection reset by peer")) {
                return Art.CLIENT_ABBRUCH;
            }
        }
        // Rollback-Hüllen erst prüfen, wenn in der Kette keine konkretere Ursache steckt
        for (Throwable t = fehler; t != null; t = t.getCause() == t ? null : t.getCause()) {
            String text = String.valueOf(t.getMessage()).toLowerCase(Locale.ROOT);
            if (t.getClass().getName().contains("Rollback") || text.contains("timed out") && text.contains("transaction")) {
                return Art.TRANSAKTION_ABGEBROCHEN;
            }
        }
        return Art.SONSTIGE;
    }

    private long wert(Art art) {
        return zaehler.get(art).get();
    }

    @Override
    public long getPoolErschoepft() {
        return wert(Art.POOL_ERSCHOEPFT);
    }

    @Override
    public long getBeanPoolTimeout() {
        return wert(Art.BEAN_POOL_TIMEOUT);
    }

    @Override
    public long getSingletonTimeout() {
        return wert(Art.SINGLETON_TIMEOUT);
    }

    @Override
    public long getSperrTimeout() {
        return wert(Art.SPERR_TIMEOUT);
    }

    @Override
    public long getAbfrageTimeout() {
        return wert(Art.ABFRAGE_TIMEOUT);
    }

    @Override
    public long getTransaktionAbgebrochen() {
        return wert(Art.TRANSAKTION_ABGEBROCHEN);
    }

    @Override
    public long getExecutorAbgelehnt() {
        return wert(Art.EXECUTOR_ABGELEHNT);
    }

    @Override
    public long getClientAbbruch() {
        return wert(Art.CLIENT_ABBRUCH);
    }

    @Override
    public long getDbSitzungslimit() {
        return wert(Art.DB_SITZUNGSLIMIT);
    }

    @Override
    public long getSonstige() {
        return wert(Art.SONSTIGE);
    }
}
