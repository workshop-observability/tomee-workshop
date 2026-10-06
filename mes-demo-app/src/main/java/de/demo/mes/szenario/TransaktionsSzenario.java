package de.demo.mes.szenario;

import java.sql.Connection;
import java.sql.PreparedStatement;
import java.util.LinkedHashMap;
import java.util.Map;

import de.demo.mes.core.DatenQuellen;
import de.demo.mes.infra.Umgebung;
import de.demo.mes.monitoring.Fehlerzaehler;
import de.demo.mes.monitoring.SzenarioStatus;
import de.demo.mes.monitoring.TransaktionsUeberwachung;
import jakarta.annotation.Resource;
import jakarta.ejb.Stateless;
import jakarta.ejb.TransactionManagement;
import jakarta.ejb.TransactionManagementType;
import jakarta.transaction.TransactionSynchronizationRegistry;
import jakarta.transaction.UserTransaction;

/**
 * Lange Transaktion mit Bean-Managed Transactions. Zeigt: Ein Transaction Timeout
 * unterbricht die Arbeit nicht – er markiert die Transaktion nur zum Rollback.
 * Sperren bleiben bis zum Ende der Methode bestehen.
 */
@Stateless
@TransactionManagement(TransactionManagementType.BEAN)
public class TransaktionsSzenario {

    @Resource
    private UserTransaction ut;

    @Resource
    private TransactionSynchronizationRegistry registry;

    /**
     * @param timeoutSekunden 0 = Default aus tomee.xml (Kunde: 14400 s)
     * @param sperreId        > 0: Baugruppe mit dieser ID wird für die gesamte Dauer gesperrt
     */
    public Map<String, Object> lang(int sekunden, int timeoutSekunden, long sperreId) throws Exception {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("dauerSekunden", sekunden);
        m.put("timeoutSekunden", timeoutSekunden == 0 ? "Default aus tomee.xml" : timeoutSekunden);
        ut.setTransactionTimeout(timeoutSekunden);
        ut.begin();
        TransaktionsUeberwachung.anmelden(registry, "TransaktionsSzenario.lang");
        SzenarioStatus.INSTANZ.langeTransaktionen.incrementAndGet();
        try {
            try (Connection c = DatenQuellen.verbinden(DatenQuellen.MES, "lange-transaktion")) {
                if (sperreId > 0) {
                    try (PreparedStatement ps = c.prepareStatement(
                            "UPDATE baugruppe SET geaendert = SYSTIMESTAMP WHERE id = ?")) {
                        ps.setLong(1, sperreId);
                        ps.executeUpdate();
                    }
                    m.put("gesperrteBaugruppe", sperreId);
                }
                Umgebung.schlafen(sekunden * 1000L);
                try (PreparedStatement ps = c.prepareStatement(
                        "INSERT INTO buchung (baugruppe_id, station, ergebnis) VALUES (?, 'LANG', 'TX')")) {
                    ps.setLong(1, Math.max(1, sperreId));
                    ps.executeUpdate();
                }
            }
            ut.commit();
            m.put("ergebnis", "committed");
        } catch (Exception e) {
            m.put("ergebnis", "zurückgerollt");
            m.put("fehlerArt", Fehlerzaehler.INSTANZ.zaehlen(e));
            m.put("meldung", e.toString());
            try {
                ut.rollback();
            } catch (Exception bereitsBeendet) {
                // commit() hat die Transaktion schon beendet
            }
        } finally {
            ut.setTransactionTimeout(0);
            SzenarioStatus.INSTANZ.langeTransaktionen.decrementAndGet();
        }
        return m;
    }
}
