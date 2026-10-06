package de.demo.mes.monitoring;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.ResultSetMetaData;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Properties;
import java.util.concurrent.ConcurrentHashMap;
import java.util.logging.Level;
import java.util.logging.Logger;

import de.demo.mes.infra.MBeans;
import de.demo.mes.infra.Umgebung;

public final class OracleSperren implements OracleSperrenMXBean {

    public static final OracleSperren INSTANZ = new OracleSperren();

    private static final Logger LOG = Logger.getLogger(OracleSperren.class.getName());

    private static final String SQL_KENNZAHLEN = """
            SELECT (SELECT COUNT(*) FROM v$session WHERE blocking_session IS NOT NULL),
                   (SELECT COUNT(DISTINCT blocking_session) FROM v$session WHERE blocking_session IS NOT NULL),
                   (SELECT NVL(MAX(wait_time_micro), 0) / 1e6 FROM v$session WHERE blocking_session IS NOT NULL),
                   (SELECT COUNT(DISTINCT object_id) FROM v$locked_object),
                   (SELECT NVL(MAX((SYSDATE - start_date) * 86400), 0) FROM v$transaction)
              FROM dual""";

    /**
     * Grenzen der Datenbank: Serverprozesse und Sessions, aktuell und laut Parameter.
     * V$RESOURCE_LIMIT ist aus der PDB nicht lesbar – deshalb gezählt. Auch Hintergrund-
     * prozesse zählen mit (Oracle Free: rund 90 von 200 schon im Leerlauf).
     */
    private static final String SQL_GRENZEN = """
            SELECT (SELECT COUNT(*) FROM v$process),
                   (SELECT TO_NUMBER(value) FROM v$parameter WHERE name = 'processes'),
                   (SELECT COUNT(*) FROM v$session),
                   (SELECT TO_NUMBER(value) FROM v$parameter WHERE name = 'sessions')
              FROM dual""";

    /** SESSIONS_PER_USER je Anwendungs-User aus seinem Profil (DEFAULT aufgelöst, -1 = unbegrenzt). */
    private static final String SQL_USER_LIMITS = """
            SELECT u.username,
                   CASE WHEN p.limit = 'UNLIMITED' THEN -1
                        WHEN p.limit = 'DEFAULT' THEN
                             (SELECT CASE WHEN d.limit = 'UNLIMITED' THEN -1 ELSE TO_NUMBER(d.limit) END
                                FROM dba_profiles d
                               WHERE d.profile = 'DEFAULT' AND d.resource_name = 'SESSIONS_PER_USER')
                        ELSE TO_NUMBER(p.limit) END
              FROM dba_users u
              JOIN dba_profiles p ON p.profile = u.profile AND p.resource_name = 'SESSIONS_PER_USER'
             WHERE u.username IN ('MES_LOCAL', 'MES_MASTER', 'MES_REPL')""";

    private static final String SQL_SITZUNGEN = """
            SELECT username,
                   COUNT(*),
                   SUM(CASE WHEN status = 'ACTIVE' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN blocking_session IS NOT NULL THEN 1 ELSE 0 END)
              FROM v$session
             WHERE username LIKE 'MES\\_%' ESCAPE '\\'
             GROUP BY username""";

    /** Blockierketten: wer wartet auf wen, auf welchem Objekt, mit welchem Statement. */
    public static final String SQL_BLOCKIERKETTEN = """
            SELECT s.sid,
                   s.serial# AS serial,
                   s.username AS benutzer,
                   s.module AS modul,
                   s.action AS aktion,
                   s.status,
                   s.blocking_session AS blockiert_durch,
                   ROUND(s.wait_time_micro / 1e6) AS wartet_sekunden,
                   s.event AS warteereignis,
                   o.owner || '.' || o.object_name AS objekt,
                   s.last_call_et AS sekunden_seit_letztem_aufruf,
                   SUBSTR(q.sql_text, 1, 120) AS sql_text
              FROM v$session s
              LEFT JOIN dba_objects o ON o.object_id = s.row_wait_obj#
              LEFT JOIN v$sql q ON q.sql_id = s.sql_id AND q.child_number = s.sql_child_number
             WHERE s.blocking_session IS NOT NULL
                OR s.sid IN (SELECT blocking_session FROM v$session WHERE blocking_session IS NOT NULL)
             ORDER BY s.blocking_session NULLS FIRST, wartet_sekunden DESC
             FETCH FIRST 50 ROWS ONLY""";

    public static final String SQL_GESPERRTE_OBJEKTE = """
            SELECT o.owner || '.' || o.object_name AS objekt,
                   s.sid, s.username AS benutzer, s.module AS modul,
                   DECODE(l.locked_mode, 0, 'none', 1, 'null', 2, 'row share', 3, 'row exclusive',
                          4, 'share', 5, 'share row exclusive', 6, 'exclusive') AS sperrmodus
              FROM v$locked_object l
              JOIN dba_objects o ON o.object_id = l.object_id
              JOIN v$session s ON s.sid = l.session_id
             ORDER BY objekt, s.sid""";

    private final Map<String, Sitzungen> sitzungen = new ConcurrentHashMap<>();
    private volatile Connection verbindung;
    private volatile int verfuegbar;
    private volatile int blockiert;
    private volatile int blockierend;
    private volatile double laengsteWartezeit;
    private volatile int gesperrteObjekte;
    private volatile double aeltesteTransaktion;
    private volatile long abfrageDauerMs;
    private volatile int dbProzesse;
    private volatile int dbProzesseLimit = -1;
    private volatile int dbSitzungen;
    private volatile int dbSitzungenLimit = -1;

    private OracleSperren() {
    }

    /** Eigene, ungepoolte Verbindung mit kurzen Timeouts. */
    public static Connection verbinden() throws SQLException {
        Properties p = new Properties();
        p.setProperty("user", Umgebung.text("MES_MONITOR_USER", "MES_MONITOR"));
        p.setProperty("password", Umgebung.text("MES_MONITOR_PASSWORD", "mes_demo"));
        p.setProperty("oracle.net.CONNECT_TIMEOUT", "5000");
        p.setProperty("oracle.jdbc.ReadTimeout", "10000");
        p.setProperty("v$session.program", "MES-Monitoring");
        return DriverManager.getConnection(Umgebung.dbUrl(), p);
    }

    /** Wird periodisch vom Überwachungs-Thread aufgerufen. */
    public void aktualisieren() {
        long start = System.currentTimeMillis();
        try {
            if (verbindung == null || verbindung.isClosed()) {
                verbindung = verbinden();
            }
            try (PreparedStatement ps = verbindung.prepareStatement(SQL_KENNZAHLEN);
                 ResultSet rs = ps.executeQuery()) {
                rs.next();
                blockiert = rs.getInt(1);
                blockierend = rs.getInt(2);
                laengsteWartezeit = rs.getDouble(3);
                gesperrteObjekte = rs.getInt(4);
                aeltesteTransaktion = rs.getDouble(5);
            }
            try (PreparedStatement ps = verbindung.prepareStatement(SQL_GRENZEN);
                 ResultSet rs = ps.executeQuery()) {
                rs.next();
                dbProzesse = rs.getInt(1);
                dbProzesseLimit = rs.getInt(2);
                dbSitzungen = rs.getInt(3);
                dbSitzungenLimit = rs.getInt(4);
            }
            Map<String, Integer> limits = new LinkedHashMap<>();
            try (PreparedStatement ps = verbindung.prepareStatement(SQL_USER_LIMITS);
                 ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    limits.put(rs.getString(1), rs.getInt(2));
                }
            }
            Map<String, int[]> neu = new LinkedHashMap<>();
            try (PreparedStatement ps = verbindung.prepareStatement(SQL_SITZUNGEN);
                 ResultSet rs = ps.executeQuery()) {
                while (rs.next()) {
                    neu.put(rs.getString(1), new int[] {rs.getInt(2), rs.getInt(3), rs.getInt(4)});
                }
            }
            for (String benutzer : List.of("MES_LOCAL", "MES_MASTER", "MES_REPL")) {
                sitzungen.computeIfAbsent(benutzer, Sitzungen::registrieren)
                        .setzen(neu.getOrDefault(benutzer, new int[3]), limits.getOrDefault(benutzer, -1));
            }
            verfuegbar = 1;
        } catch (SQLException e) {
            verfuegbar = 0;
            LOG.log(Level.FINE, "Oracle-Sperren nicht lesbar", e);
            schliessen();
        } finally {
            abfrageDauerMs = System.currentTimeMillis() - start;
        }
    }

    public void schliessen() {
        try {
            if (verbindung != null) {
                verbindung.close();
            }
        } catch (SQLException ignoriert) {
            // Verbindung ist ohnehin kaputt
        }
        verbindung = null;
    }

    /** Führt eine Diagnoseabfrage mit frischer Verbindung aus (für die REST-Diagnose). */
    public static List<Map<String, Object>> abfragen(String sql) throws SQLException {
        try (Connection c = verbinden();
             PreparedStatement ps = c.prepareStatement(sql)) {
            ps.setQueryTimeout(10);
            try (ResultSet rs = ps.executeQuery()) {
                ResultSetMetaData meta = rs.getMetaData();
                List<Map<String, Object>> zeilen = new ArrayList<>();
                while (rs.next()) {
                    Map<String, Object> zeile = new LinkedHashMap<>();
                    for (int i = 1; i <= meta.getColumnCount(); i++) {
                        Object wert = rs.getObject(i);
                        zeile.put(meta.getColumnLabel(i).toLowerCase(), wert == null ? null : wert.toString());
                    }
                    zeilen.add(zeile);
                }
                return zeilen;
            }
        }
    }

    @Override
    public int getVerfuegbar() {
        return verfuegbar;
    }

    @Override
    public int getBlockierteSessions() {
        return blockiert;
    }

    @Override
    public int getBlockierendeSessions() {
        return blockierend;
    }

    @Override
    public double getLaengsteWartezeitSekunden() {
        return laengsteWartezeit;
    }

    @Override
    public int getGesperrteObjekte() {
        return gesperrteObjekte;
    }

    @Override
    public double getAeltesteTransaktionSekunden() {
        return aeltesteTransaktion;
    }

    @Override
    public long getAbfrageDauerMs() {
        return abfrageDauerMs;
    }

    @Override
    public int getDbProzesse() {
        return dbProzesse;
    }

    @Override
    public int getDbProzesseLimit() {
        return dbProzesseLimit;
    }

    @Override
    public int getDbSitzungen() {
        return dbSitzungen;
    }

    @Override
    public int getDbSitzungenLimit() {
        return dbSitzungenLimit;
    }

    private static final class Sitzungen implements OracleSitzungenMXBean {

        private final String benutzer;
        private volatile int[] werte = new int[3];
        private volatile int limit = -1;

        private Sitzungen(String benutzer) {
            this.benutzer = benutzer;
        }

        static Sitzungen registrieren(String benutzer) {
            Sitzungen s = new Sitzungen(benutzer);
            MBeans.registrieren(s, "type=OracleSitzungen,benutzer=" + benutzer);
            return s;
        }

        void setzen(int[] neu, int neuesLimit) {
            werte = neu;
            limit = neuesLimit;
        }

        @Override
        public String getBenutzer() {
            return benutzer;
        }

        @Override
        public int getGesamt() {
            return werte[0];
        }

        @Override
        public int getAktiv() {
            return werte[1];
        }

        @Override
        public int getInaktiv() {
            return werte[0] - werte[1];
        }

        @Override
        public int getBlockiert() {
            return werte[2];
        }

        @Override
        public int getLimit() {
            return limit;
        }
    }
}
