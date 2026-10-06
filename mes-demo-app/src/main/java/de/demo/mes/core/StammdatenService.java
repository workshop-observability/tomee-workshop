package de.demo.mes.core;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

import de.demo.mes.monitoring.TransaktionsUeberwachung;
import jakarta.ejb.Stateless;
import jakarta.interceptor.Interceptors;

/**
 * Stammdatenversorgung: liest aus der Master-DB und schreibt in die lokale DB.
 * Wird vom Singleton-Timer periodisch aufgerufen (beim Kunden alle 5 Minuten).
 */
@Stateless
@Interceptors(TransaktionsUeberwachung.class)
public class StammdatenService {

    public Map<String, Object> abgleichen() throws SQLException {
        long artikelId = ThreadLocalRandom.current().nextLong(1, 2001);
        String artikel;
        try (Connection master = DatenQuellen.verbinden(DatenQuellen.MASTER, "stammdaten-lesen");
             PreparedStatement ps = master.prepareStatement("SELECT artikel FROM stammdaten WHERE id = ?")) {
            ps.setLong(1, artikelId);
            try (ResultSet rs = ps.executeQuery()) {
                artikel = rs.next() ? rs.getString(1) : "ART-0";
            }
        }
        long baugruppe = ThreadLocalRandom.current().nextLong(1, 10001);
        try (Connection lokal = DatenQuellen.verbinden(DatenQuellen.MES, "stammdaten-abgleich");
             PreparedStatement ps = lokal.prepareStatement(
                     "UPDATE baugruppe SET artikel = ?, geaendert = SYSTIMESTAMP WHERE id = ?")) {
            ps.setString(1, artikel);
            ps.setLong(2, baugruppe);
            ps.executeUpdate();
        }
        return Map.of("artikel", artikel, "baugruppe", baugruppe);
    }

    /** Liest einen Stammsatz aus der Master-DB. Oracle-Leser warten nie auf Sperren – wohl aber auf eine Connection. */
    public Map<String, Object> masterLesen() throws SQLException {
        long id = ThreadLocalRandom.current().nextLong(1, 2001);
        try (Connection master = DatenQuellen.verbinden(DatenQuellen.MASTER, "stammdaten-lesen");
             PreparedStatement ps = master.prepareStatement(
                     "SELECT artikel, bezeichnung, version FROM stammdaten WHERE id = ?")) {
            ps.setLong(1, id);
            try (ResultSet rs = ps.executeQuery()) {
                return rs.next()
                        ? Map.of("id", id, "artikel", rs.getString(1), "version", rs.getLong(3))
                        : Map.of("id", id, "gefunden", false);
            }
        }
    }

    /** Schreibt in die Master-DB (Pool mit nur 20 Connections). */
    public Map<String, Object> masterSchreiben() throws SQLException {
        long id = ThreadLocalRandom.current().nextLong(1, 2001);
        try (Connection master = DatenQuellen.verbinden(DatenQuellen.MASTER, "stammdaten-schreiben");
             PreparedStatement ps = master.prepareStatement(
                     "UPDATE stammdaten SET version = version + 1, geaendert = SYSTIMESTAMP WHERE id = ?")) {
            ps.setLong(1, id);
            ps.executeUpdate();
        }
        return Map.of("stammdatenId", id);
    }
}
