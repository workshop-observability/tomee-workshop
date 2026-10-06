package de.demo.mes.fileprocessing;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.sql.Connection;
import java.sql.PreparedStatement;
import java.sql.SQLException;

import de.demo.mes.core.DatenQuellen;
import de.demo.mes.infra.Umgebung;
import de.demo.mes.monitoring.TransaktionsUeberwachung;
import jakarta.ejb.Stateless;
import jakarta.interceptor.Interceptors;

/**
 * Verarbeitet eine empfangene Protokolldatei. Läuft laut WEB-INF/openejb-jar.xml im
 * „FileContentHandling Container“ (maxSize 100) – ein eigener Bean-Pool wie beim Kunden.
 */
@Stateless
@Interceptors(TransaktionsUeberwachung.class)
public class DateiInhaltVerarbeitung {

    /** Künstliche Verarbeitungszeit je Datei. */
    private static final long VERZOEGERUNG_MS = 50;

    public int verarbeiten(Path datei, String station) throws IOException, SQLException {
        int zeilen;
        try (var lines = Files.lines(datei)) {
            zeilen = (int) lines.count();
        }
        Umgebung.schlafen(VERZOEGERUNG_MS);
        try (Connection c = DatenQuellen.verbinden(DatenQuellen.MES, "datei-verarbeitung");
             PreparedStatement ps = c.prepareStatement(
                     "INSERT INTO buchung (baugruppe_id, station, ergebnis) VALUES (?, ?, 'DATEI')")) {
            ps.setLong(1, Math.max(1, Math.abs(datei.getFileName().toString().hashCode()) % 10000));
            ps.setString(2, station);
            ps.executeUpdate();
        }
        return zeilen;
    }
}
