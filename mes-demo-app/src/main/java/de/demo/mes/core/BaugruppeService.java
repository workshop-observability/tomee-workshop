package de.demo.mes.core;

import java.sql.CallableStatement;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.LinkedHashMap;
import java.util.Map;

import de.demo.mes.monitoring.TransaktionsUeberwachung;
import jakarta.ejb.Stateless;
import jakarta.interceptor.Interceptors;

/**
 * Nachbildung eines Core-Anwendungsfalls („Gib mir den Zustand einer Baugruppe“).
 * Läuft im „Default Stateless Container“ (maxSize 50, strictPooling, accessTimeout 30 s).
 */
@Stateless
@Interceptors(TransaktionsUeberwachung.class)
public class BaugruppeService {

    /** Reiner Lesezugriff. Oracle-Leser warten nie auf Sperren (Multiversion Read Consistency). */
    public Map<String, Object> lesen(long id) throws SQLException {
        try (Connection c = DatenQuellen.verbinden(DatenQuellen.MES, "lesen");
             PreparedStatement ps = c.prepareStatement(
                     "SELECT id, seriennummer, artikel, status, station, buchungen, geaendert FROM baugruppe WHERE id = ?")) {
            ps.setLong(1, id);
            try (ResultSet rs = ps.executeQuery()) {
                Map<String, Object> m = new LinkedHashMap<>();
                if (rs.next()) {
                    m.put("id", rs.getLong(1));
                    m.put("seriennummer", rs.getString(2));
                    m.put("artikel", rs.getString(3));
                    m.put("status", rs.getString(4));
                    m.put("station", rs.getString(5));
                    m.put("buchungen", rs.getLong(6));
                    m.put("geaendert", String.valueOf(rs.getTimestamp(7)));
                }
                return m;
            }
        }
    }

    /**
     * Schreibender Zugriff: sperrt die Zeile und bucht. Genau hier hängt die
     * Anwendung, wenn die Replikation die Tabelle gesperrt hat.
     *
     * @param warteSekunden   null = unbegrenzt warten (Verhalten beim Kunden),
     *                        sonst {@code FOR UPDATE WAIT n} → ORA-30006 nach n Sekunden
     * @param abfrageTimeout  null = kein Statement-Timeout, sonst {@code setQueryTimeout}
     */
    public Map<String, Object> buchen(long id, String station, Integer warteSekunden, Integer abfrageTimeout)
            throws SQLException {
        String sperre = "SELECT buchungen FROM baugruppe WHERE id = ? FOR UPDATE"
                + (warteSekunden == null ? "" : " WAIT " + Math.max(0, warteSekunden));
        try (Connection c = DatenQuellen.verbinden(DatenQuellen.MES, "buchung")) {
            long buchungen;
            try (PreparedStatement ps = c.prepareStatement(sperre)) {
                if (abfrageTimeout != null) {
                    ps.setQueryTimeout(abfrageTimeout);
                }
                ps.setLong(1, id);
                try (ResultSet rs = ps.executeQuery()) {
                    if (!rs.next()) {
                        return Map.of("id", id, "gefunden", false);
                    }
                    buchungen = rs.getLong(1) + 1;
                }
            }
            try (PreparedStatement ps = c.prepareStatement(
                    "UPDATE baugruppe SET buchungen = ?, station = ?, geaendert = SYSTIMESTAMP WHERE id = ?")) {
                ps.setLong(1, buchungen);
                ps.setString(2, station);
                ps.setLong(3, id);
                ps.executeUpdate();
            }
            try (PreparedStatement ps = c.prepareStatement(
                    "INSERT INTO buchung (baugruppe_id, station, ergebnis) VALUES (?, ?, 'OK')")) {
                ps.setLong(1, id);
                ps.setString(2, station);
                ps.executeUpdate();
            }
            return Map.of("id", id, "buchungen", buchungen, "station", station);
        }
    }

    /** Hält eine Connection {@code sekunden} lang mit einer laufenden Abfrage belegt – ohne Sperre. */
    public Map<String, Object> langsameAbfrage(String dataSource, int sekunden) throws SQLException {
        long start = System.currentTimeMillis();
        try (Connection c = DatenQuellen.verbinden(dataSource, "langsame-abfrage");
             CallableStatement cs = c.prepareCall("BEGIN DBMS_SESSION.SLEEP(?); END;")) {
            cs.setInt(1, sekunden);
            cs.execute();
        }
        return Map.of("dataSource", dataSource, "dauerMs", System.currentTimeMillis() - start);
    }
}
