package de.demo.mes.szenario;

import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Statement;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Properties;
import java.util.concurrent.CopyOnWriteArrayList;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.logging.Logger;

import de.demo.mes.core.DatenQuellen;
import de.demo.mes.infra.Umgebung;
import de.demo.mes.monitoring.SzenarioStatus;
import jakarta.ejb.ConcurrencyManagement;
import jakarta.ejb.ConcurrencyManagementType;
import jakarta.ejb.Singleton;
import jakarta.ejb.TransactionAttribute;
import jakarta.ejb.TransactionAttributeType;

/**
 * Datenbank-Störungen: Sperren durch die „Replikation“ (S01, S06), Connection-Leck (S18)
 * und eine Sitzungsgrenze auf Oracle-Seite (S15).
 */
@Singleton
@ConcurrencyManagement(ConcurrencyManagementType.BEAN)
@TransactionAttribute(TransactionAttributeType.NOT_SUPPORTED)
public class DbSzenarien {

    private static final Logger LOG = Logger.getLogger(DbSzenarien.class.getName());
    private static final Map<String, String> TABELLEN = Map.of(
            "BAUGRUPPE", "mes_local.baugruppe",
            "BUCHUNG", "mes_local.buchung",
            "STAMMDATEN", "mes_master.stammdaten");

    private record Sperre(Thread thread, String beschreibung, long startMs) {
    }

    private static final String PROFIL = "MES_SITZUNGEN";
    private static final List<String> BENUTZER = List.of("MES_LOCAL", "MES_MASTER");

    private final List<Sperre> sperren = new CopyOnWriteArrayList<>();
    private final AtomicInteger nummer = new AtomicInteger();
    private final List<Connection> geleckt = new CopyOnWriteArrayList<>();

    /**
     * Simuliert den Replikationsprozess: eine fremde Session (User MES_REPL, nicht aus
     * dem Anwendungs-Pool) sperrt eine Tabelle oder einen Zeilenbereich.
     *
     * @param modus {@code tabelle} (LOCK TABLE … IN EXCLUSIVE MODE) oder
     *              {@code zeilen} (SELECT … FOR UPDATE für die IDs von–bis)
     */
    public Map<String, Object> sperren(String tabelle, String modus, long von, long bis, int sekunden)
            throws InterruptedException {
        String objekt = TABELLEN.get(tabelle.toUpperCase(Locale.ROOT));
        if (objekt == null) {
            throw new IllegalArgumentException("Tabelle muss eine von " + TABELLEN.keySet() + " sein");
        }
        boolean ganzeTabelle = !"zeilen".equalsIgnoreCase(modus);
        String sql = ganzeTabelle
                ? "LOCK TABLE " + objekt + " IN EXCLUSIVE MODE"
                : "SELECT id FROM " + objekt + " WHERE id BETWEEN ? AND ? FOR UPDATE";
        String beschreibung = ganzeTabelle ? objekt + " (ganze Tabelle)" : objekt + " IDs " + von + "–" + bis;
        CountDownLatch gesperrt = new CountDownLatch(1);
        List<String> fehler = new CopyOnWriteArrayList<>();

        Thread thread = new Thread(() -> {
            Sperre eintrag = new Sperre(Thread.currentThread(), beschreibung, System.currentTimeMillis());
            sperren.add(eintrag);
            SzenarioStatus.INSTANZ.sperren.incrementAndGet();
            try (Connection c = replikationsVerbindung()) {
                c.setAutoCommit(false);
                try (PreparedStatement ps = c.prepareStatement(sql)) {
                    if (!ganzeTabelle) {
                        ps.setLong(1, von);
                        ps.setLong(2, bis);
                    }
                    ps.execute();
                }
                gesperrt.countDown();
                LOG.info("Sperre gesetzt: " + beschreibung + " für " + sekunden + " s");
                try {
                    TimeUnit.SECONDS.sleep(sekunden);
                } catch (InterruptedException e) {
                    LOG.info("Sperre vorzeitig freigegeben: " + beschreibung);
                }
                c.rollback();
            } catch (SQLException e) {
                fehler.add(e.getMessage());
            } finally {
                sperren.remove(eintrag);
                SzenarioStatus.INSTANZ.sperren.decrementAndGet();
                gesperrt.countDown();
            }
        }, "replikation-sperre-" + nummer.incrementAndGet());
        thread.setDaemon(true);
        thread.start();

        boolean erreicht = gesperrt.await(10, TimeUnit.SECONDS);
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("sperre", beschreibung);
        m.put("sekunden", sekunden);
        m.put("status", !fehler.isEmpty() ? "fehler: " + fehler.get(0)
                : erreicht ? "gesetzt" : "wartet selbst auf eine andere Sperre");
        return m;
    }

    public List<Map<String, Object>> sperrenAuflisten() {
        long jetzt = System.currentTimeMillis();
        List<Map<String, Object>> liste = new ArrayList<>();
        for (Sperre s : sperren) {
            liste.add(Map.of("sperre", s.beschreibung(), "seitSekunden", (jetzt - s.startMs()) / 1000));
        }
        return liste;
    }

    public int sperrenFreigeben() {
        int anzahl = sperren.size();
        sperren.forEach(s -> s.thread().interrupt());
        return anzahl;
    }

    // ─── S18: Connection-Leck ──────────────────────────────────────────────

    /**
     * Leiht {@code anzahl} Connections aus und gibt sie nie zurück – wie ein Codepfad ohne
     * {@code close()}. In Oracle stehen die Sessions dann INACTIVE, der Pool hält sie für belegt.
     */
    public Map<String, Object> leck(String dataSource, int anzahl) throws SQLException {
        int neu = 0;
        String fehler = null;
        for (int i = 0; i < anzahl; i++) {
            try {
                geleckt.add(DatenQuellen.verbinden(dataSource, "leck"));
                SzenarioStatus.INSTANZ.geleckteConnections.incrementAndGet();
                neu++;
            } catch (SQLException | RuntimeException e) {
                fehler = e.toString();
                break;
            }
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("dataSource", dataSource);
        m.put("neuGeleckt", neu);
        m.put("geleckt", geleckt.size());
        if (fehler != null) {
            m.put("fehler", fehler);
        }
        return m;
    }

    public int leckSchliessen() {
        int anzahl = 0;
        for (Connection c : geleckt) {
            try {
                c.close();
            } catch (SQLException ignoriert) {
                // vom Pool evtl. schon als abandoned geschlossen
            }
            geleckt.remove(c);
            SzenarioStatus.INSTANZ.geleckteConnections.decrementAndGet();
            anzahl++;
        }
        return anzahl;
    }

    // ─── S15: Sitzungsgrenze der Datenbank ────────────────────────────────

    /**
     * Setzt in Oracle eine Grenze für gleichzeitige Sessions eines Users (Profil
     * {@value #PROFIL}, SESSIONS_PER_USER). Wer darüber hinaus eine Connection öffnen will,
     * bekommt sofort ORA-02391 – egal, wie viel Luft der eigene Pool noch hat.
     *
     * @param limit 0 = unbegrenzt
     */
    public Map<String, Object> sitzungslimit(String benutzer, int limit) throws SQLException {
        String user = benutzer.toUpperCase(Locale.ROOT);
        if (!BENUTZER.contains(user)) {
            throw new IllegalArgumentException("benutzer muss einer von " + BENUTZER + " sein");
        }
        String wert = limit > 0 ? String.valueOf(limit) : "UNLIMITED";
        try (Connection c = dbaVerbindung(); Statement st = c.createStatement()) {
            try {
                st.execute("CREATE PROFILE " + PROFIL + " LIMIT SESSIONS_PER_USER UNLIMITED");
            } catch (SQLException e) {
                if (e.getErrorCode() != 2379) {
                    throw e;
                }
            }
            st.execute("ALTER PROFILE " + PROFIL + " LIMIT SESSIONS_PER_USER " + wert);
            st.execute("ALTER USER " + user + " PROFILE " + PROFIL);
            LOG.info("Sitzungsgrenze für " + user + ": " + wert);
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("benutzer", user);
            m.put("sessionsPerUser", wert);
            try (ResultSet rs = st.executeQuery(
                    "SELECT value FROM v$parameter WHERE name = 'resource_limit'")) {
                m.put("resource_limit", rs.next() ? rs.getString(1) : "?");
            }
            return m;
        }
    }

    /** Hebt die Grenze wieder auf (das Profil bleibt zugeordnet, steht dann auf UNLIMITED). */
    public String sitzungslimitAufheben() {
        try (Connection c = dbaVerbindung(); Statement st = c.createStatement()) {
            st.execute("ALTER PROFILE " + PROFIL + " LIMIT SESSIONS_PER_USER UNLIMITED");
            return "aufgehoben";
        } catch (SQLException e) {
            // ORA-02380: Profil gibt es noch nicht – dann gab es auch keine Grenze
            return e.getErrorCode() == 2380 ? "keine gesetzt" : "fehler: " + e.getMessage();
        }
    }

    /** Administrative Verbindung (Demo: SYSTEM) – nur für das Setzen der Grenze. */
    private static Connection dbaVerbindung() throws SQLException {
        Properties p = new Properties();
        p.setProperty("user", Umgebung.text("MES_DBA_USER", "SYSTEM"));
        p.setProperty("password", Umgebung.text("MES_DBA_PASSWORD", "oracle_demo"));
        p.setProperty("oracle.net.CONNECT_TIMEOUT", "5000");
        p.setProperty("oracle.jdbc.ReadTimeout", "30000");
        return DriverManager.getConnection(Umgebung.dbUrl(), p);
    }

    private static Connection replikationsVerbindung() throws SQLException {
        Properties p = new Properties();
        p.setProperty("user", Umgebung.text("MES_REPL_USER", "MES_REPL"));
        p.setProperty("password", Umgebung.text("MES_REPL_PASSWORD", "mes_demo"));
        p.setProperty("v$session.program", "Replikation");
        Connection c = DriverManager.getConnection(Umgebung.dbUrl(), p);
        try {
            c.setClientInfo("OCSID.MODULE", "REPLIKATION");
            c.setClientInfo("OCSID.ACTION", "sperre");
        } catch (SQLException ignoriert) {
            // nur Komfort für die Diagnose
        }
        return c;
    }
}
