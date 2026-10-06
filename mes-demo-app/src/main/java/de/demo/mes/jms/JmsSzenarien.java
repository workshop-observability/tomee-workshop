package de.demo.mes.jms;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;
import java.util.concurrent.atomic.AtomicLong;

import de.demo.mes.monitoring.MdbStatistik;
import jakarta.annotation.Resource;
import jakarta.ejb.ConcurrencyManagement;
import jakarta.ejb.ConcurrencyManagementType;
import jakarta.ejb.Singleton;
import jakarta.ejb.TransactionAttribute;
import jakarta.ejb.TransactionAttributeType;
import jakarta.jms.ConnectionFactory;
import jakarta.jms.JMSConsumer;
import jakarta.jms.JMSContext;
import jakarta.jms.JMSException;
import jakarta.jms.JMSProducer;
import jakarta.jms.Message;
import jakarta.jms.Queue;

/**
 * Nachrichten für S12 erzeugen und den Rückstand wieder abbauen. Sendet über die
 * „Default JMS Connection Factory“ von TomEE (PoolMaxSize 10) an den Broker aus
 * {@code MES_JMS_URL}.
 */
@Singleton
@ConcurrencyManagement(ConcurrencyManagementType.BEAN)
@TransactionAttribute(TransactionAttributeType.NOT_SUPPORTED)
public class JmsSzenarien {

    public static final String QUEUE = "MES.EINGANG";
    public static final String DLQ = "ActiveMQ.DLQ";
    public static final List<String> ARTEN = List.of("langsam", "buchung");

    /** Nach dem Leeren: noch zugestellte Nachrichten sofort bestätigen statt verarbeiten. */
    static volatile boolean verwerfen;

    private final AtomicLong gesendet = new AtomicLong();

    @Resource
    private ConnectionFactory fabrik;

    /**
     * @param art         {@code langsam}: Verarbeitung dauert {@code ms}; {@code buchung}: bucht
     *                    auf eine zufällige Baugruppe (hängt bei einer Tabellensperre)
     * @param giftProzent Anteil Nachrichten, deren Verarbeitung immer scheitert
     */
    public Map<String, Object> senden(int anzahl, String art, long ms, int giftProzent) {
        String typ = art.toLowerCase(Locale.ROOT);
        if (!ARTEN.contains(typ)) {
            throw new IllegalArgumentException("art muss eine von " + ARTEN + " sein");
        }
        verwerfen = false;
        int gift = 0;
        try (JMSContext ctx = fabrik.createContext()) {
            Queue queue = ctx.createQueue(QUEUE);
            JMSProducer producer = ctx.createProducer();
            for (int i = 0; i < anzahl; i++) {
                Message m = ctx.createTextMessage("MES-Nachricht " + gesendet.incrementAndGet());
                boolean istGift = ThreadLocalRandom.current().nextInt(100) < giftProzent;
                m.setStringProperty("art", typ);
                m.setLongProperty("ms", ms);
                m.setLongProperty("baugruppe", ThreadLocalRandom.current().nextLong(1, 10_001));
                m.setBooleanProperty("gift", istGift);
                producer.send(queue, m);
                if (istGift) {
                    gift++;
                }
            }
        } catch (JMSException e) {
            throw new IllegalStateException("Senden an " + QUEUE + " fehlgeschlagen: " + e.getMessage(), e);
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("gesendet", anzahl);
        m.put("davonGift", gift);
        m.put("gesendetGesamt", gesendet.get());
        return m;
    }

    /**
     * Baut den Rückstand ab: noch zugestellte Nachrichten werden sofort bestätigt, die Queue
     * und die Dead Letter Queue werden leergelesen.
     */
    public Map<String, Object> leeren() {
        verwerfen = true;
        Map<String, Object> m = new LinkedHashMap<>();
        m.put(QUEUE, leerlesen(QUEUE));
        m.put(DLQ, leerlesen(DLQ));
        return m;
    }

    private int leerlesen(String name) {
        int anzahl = 0;
        long ende = System.currentTimeMillis() + 20_000;
        try (JMSContext ctx = fabrik.createContext(JMSContext.AUTO_ACKNOWLEDGE);
             JMSConsumer consumer = ctx.createConsumer(ctx.createQueue(name))) {
            int leer = 0;
            while (leer < 2 && System.currentTimeMillis() < ende) {
                if (consumer.receive(500) == null) {
                    leer++;
                } else {
                    leer = 0;
                    anzahl++;
                }
            }
        } catch (RuntimeException e) {
            return -1;
        }
        return anzahl;
    }

    public Map<String, Object> zustand() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("queue", QUEUE);
        m.put("gesendetGesamt", gesendet.get());
        m.put("verwerfen", verwerfen);
        MdbStatistik.alle().forEach((name, s) -> {
            Map<String, Object> mdb = new LinkedHashMap<>();
            mdb.put("aktiv", s.getAktiv());
            mdb.put("verarbeitet", s.getVerarbeitet());
            mdb.put("fehler", s.getFehler());
            mdb.put("wiederholungen", s.getWiederholungen());
            mdb.put("letzteWartezeitSekunden", s.getLetzteWartezeitSekunden());
            m.put(name, mdb);
        });
        return m;
    }
}
