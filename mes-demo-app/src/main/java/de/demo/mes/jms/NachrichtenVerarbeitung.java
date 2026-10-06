package de.demo.mes.jms;

import java.sql.SQLException;

import de.demo.mes.core.BaugruppeService;
import de.demo.mes.infra.Umgebung;
import de.demo.mes.monitoring.MdbStatistik;
import jakarta.ejb.ActivationConfigProperty;
import jakarta.ejb.EJB;
import jakarta.ejb.MessageDriven;
import jakarta.jms.JMSException;
import jakarta.jms.Message;
import jakarta.jms.MessageListener;

/**
 * Holt Nachrichten aus der Queue {@value JmsSzenarien#QUEUE} – wie der Applikationsserver
 * beim Kunden („AppServer holt Nachrichten aus Queue“).
 *
 * <p>Keine eigene Container-Konfiguration: Es gelten die TomEE-Defaults des
 * „Default MDB Container“ ({@code InstanceLimit 10}) und des ActiveMQ-Resource-Adapters
 * ({@code maxSessions 10}) – höchstens zehn Nachrichten gleichzeitig je JVM. Welcher
 * Applikationsserver konsumiert, steuert {@code MES_JMS_KONSUMENT} (setenv.sh).
 */
@MessageDriven(name = "NachrichtenVerarbeitung", activationConfig = {
        @ActivationConfigProperty(propertyName = "destinationType", propertyValue = "jakarta.jms.Queue"),
        @ActivationConfigProperty(propertyName = "destination", propertyValue = JmsSzenarien.QUEUE)})
public class NachrichtenVerarbeitung implements MessageListener {

    @EJB
    private BaugruppeService baugruppen;

    @Override
    public void onMessage(Message nachricht) {
        MdbStatistik statistik = MdbStatistik.fuer("NachrichtenVerarbeitung");
        long start = statistik.begonnen(zeitstempel(nachricht), wiederholt(nachricht));
        boolean erfolgreich = false;
        try {
            if (!JmsSzenarien.verwerfen) {
                verarbeiten(nachricht);
            }
            erfolgreich = true;
        } catch (JMSException e) {
            throw new IllegalStateException("Nachricht nicht lesbar", e);
        } finally {
            statistik.beendet(start, erfolgreich);
        }
    }

    private void verarbeiten(Message nachricht) throws JMSException {
        if (nachricht.getBooleanProperty("gift")) {
            // Die Transaktion wird zurückgerollt, der Broker stellt erneut zu – nach
            // maximumRedeliveries (ActiveMQ-Default 6) landet die Nachricht in ActiveMQ.DLQ
            throw new IllegalStateException("Nachricht nicht verarbeitbar (Gift)");
        }
        if ("buchung".equals(nachricht.getStringProperty("art"))) {
            try {
                baugruppen.buchen(nachricht.getLongProperty("baugruppe"), "JMS", null, null);
            } catch (SQLException e) {
                throw new IllegalStateException(e);
            }
        } else {
            Umgebung.schlafen(nachricht.getLongProperty("ms"));
        }
    }

    private static long zeitstempel(Message nachricht) {
        try {
            return nachricht.getJMSTimestamp();
        } catch (JMSException e) {
            return 0;
        }
    }

    private static boolean wiederholt(Message nachricht) {
        try {
            return nachricht.getJMSRedelivered();
        } catch (JMSException e) {
            return false;
        }
    }
}
