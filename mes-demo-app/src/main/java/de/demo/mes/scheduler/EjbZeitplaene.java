package de.demo.mes.scheduler;

import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;
import java.util.logging.Logger;

import de.demo.mes.core.StammdatenService;
import de.demo.mes.infra.Umgebung;
import de.demo.mes.monitoring.Fehlerzaehler;
import de.demo.mes.monitoring.SchedulerJob;
import de.demo.mes.monitoring.SzenarioStatus;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.Resource;
import jakarta.ejb.EJB;
import jakarta.ejb.Lock;
import jakarta.ejb.LockType;
import jakarta.ejb.ScheduleExpression;
import jakarta.ejb.Singleton;
import jakarta.ejb.Startup;
import jakarta.ejb.Timeout;
import jakarta.ejb.Timer;
import jakarta.ejb.TimerConfig;
import jakarta.ejb.TimerService;
import jakarta.ejb.TransactionAttribute;
import jakarta.ejb.TransactionAttributeType;

/**
 * EJB-Timer. TomEE führt sie intern mit einem geshadeten Quartz aus – alle Timer
 * der JVM teilen sich den Pool „EjbTimerPool“, Größe {@code openejb.timer.pool.size}
 * (Default 3). Hängen drei Timer-Läufe an der Datenbank, tickt kein Timer mehr.
 */
@Singleton
@Startup
@Lock(LockType.READ)
public class EjbZeitplaene {

    private static final Logger LOG = Logger.getLogger(EjbZeitplaene.class.getName());
    private static final int HEARTBEAT_SEKUNDEN = Umgebung.zahl("HEARTBEAT_SEKUNDEN", 10);
    private static final int ABGLEICH_MINUTEN = Umgebung.zahl("ABGLEICH_MINUTEN", 1);
    private static final String BLOCKIERER = "blockierer:";
    private static final String LANGLAEUFER = "langlaeufer";
    public static final List<String> SCHUTZ = List.of("ohne", "ueberspringen", "singleton-lock");

    // Einstellungen des Langläufers (S11); gelten für alle Läufe dieser JVM
    private static volatile long langlaeuferMs;
    private static volatile String langlaeuferSchutz = "ohne";
    private static final AtomicBoolean LANGLAEUFER_LAEUFT = new AtomicBoolean();

    @Resource
    private TimerService timerService;

    @EJB
    private StammdatenService stammdaten;

    @EJB
    private SchreibSingleton schreibSingleton;

    @PostConstruct
    void planen() {
        SchedulerJob.fuer("ejb", "heartbeat", HEARTBEAT_SEKUNDEN);
        SchedulerJob.fuer("ejb", "stammdatenabgleich", ABGLEICH_MINUTEN * 60L);
        timerService.createCalendarTimer(
                new ScheduleExpression().hour("*").minute("*").second("*/" + HEARTBEAT_SEKUNDEN),
                new TimerConfig("heartbeat", false));
        timerService.createCalendarTimer(
                new ScheduleExpression().hour("*").minute("*/" + ABGLEICH_MINUTEN).second("0"),
                new TimerConfig("stammdatenabgleich", false));
    }

    /** Ohne eigene Transaktion: Der Abgleich startet seine eigene im StammdatenService. */
    @Timeout
    @TransactionAttribute(TransactionAttributeType.NOT_SUPPORTED)
    public void ausfuehren(Timer timer) {
        String info = String.valueOf(timer.getInfo());
        if (info.startsWith(BLOCKIERER)) {
            blockieren(Long.parseLong(info.substring(BLOCKIERER.length())));
            return;
        }
        if (LANGLAEUFER.equals(info)) {
            langlaeufer();
            return;
        }
        SchedulerJob job = SchedulerJob.fuer("ejb", info, 0);
        long start = job.gestartet(0);
        boolean erfolgreich = false;
        try {
            if ("stammdatenabgleich".equals(info)) {
                stammdaten.abgleichen();
            }
            erfolgreich = true;
        } catch (Exception e) {
            Fehlerzaehler.INSTANZ.zaehlen(e);
            LOG.warning("EJB-Timer " + info + " fehlgeschlagen: " + e);
        } finally {
            job.beendet(start, erfolgreich);
        }
    }

    /** Belegt {@code anzahl} Timer-Threads für {@code ms} Millisekunden. */
    public void blockierenEinplanen(int anzahl, long ms) {
        for (int i = 0; i < anzahl; i++) {
            timerService.createSingleActionTimer(1, new TimerConfig(BLOCKIERER + ms, false));
        }
    }

    /**
     * Periodischer Job, der länger laufen kann als sein Intervall – wie ein Abgleich, der
     * „manchmal keine Zeit bekommt“ (S11).
     *
     * @param schutz {@code ohne}: jeder fällige Lauf startet, Läufe überlappen und belegen
     *               Laufzeit ÷ Intervall Timer-Threads; {@code ueberspringen}: läuft der vorige
     *               noch, entfällt der Termin; {@code singleton-lock}: die Arbeit steckt in einem
     *               {@code @Singleton} mit Schreibsperre (Default) – fällige Läufe warten auf die
     *               Sperre und halten dabei ihren Timer-Thread
     */
    public Map<String, Object> langlaeuferStarten(int intervallSekunden, int laufzeitSekunden, String schutz) {
        String modus = schutz.toLowerCase(Locale.ROOT);
        if (!SCHUTZ.contains(modus)) {
            throw new IllegalArgumentException("schutz muss einer von " + SCHUTZ + " sein");
        }
        int gestoppt = langlaeuferStoppen();
        langlaeuferMs = laufzeitSekunden * 1000L;
        langlaeuferSchutz = modus;
        SchedulerJob.fuer("ejb", LANGLAEUFER, intervallSekunden).setSollIntervallSekunden(intervallSekunden);
        long intervallMs = intervallSekunden * 1000L;
        timerService.createIntervalTimer(intervallMs, intervallMs, new TimerConfig(LANGLAEUFER, false));
        LOG.info("Langläufer: alle " + intervallSekunden + " s, Laufzeit " + laufzeitSekunden + " s, Schutz " + modus);
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("intervallSekunden", intervallSekunden);
        m.put("laufzeitSekunden", laufzeitSekunden);
        m.put("schutz", modus);
        m.put("timerPool", System.getProperty("openejb.timer.pool.size", "3 (Default)"));
        m.put("ersetzt", gestoppt);
        return m;
    }

    /** Beendet die Planung; laufende Läufe arbeiten zu Ende. */
    public int langlaeuferStoppen() {
        int anzahl = 0;
        for (Timer t : timerService.getTimers()) {
            if (LANGLAEUFER.equals(String.valueOf(t.getInfo()))) {
                t.cancel();
                anzahl++;
            }
        }
        return anzahl;
    }

    private void langlaeufer() {
        SchedulerJob job = SchedulerJob.fuer("ejb", LANGLAEUFER, 0);
        switch (langlaeuferSchutz) {
            case "ueberspringen" -> {
                if (!LANGLAEUFER_LAEUFT.compareAndSet(false, true)) {
                    job.uebersprungen();
                    return;
                }
                try {
                    arbeiten(job, langlaeuferMs);
                } finally {
                    LANGLAEUFER_LAEUFT.set(false);
                }
            }
            case "singleton-lock" -> {
                // wartet ist true, bis der Singleton die Sperre vergeben hat
                AtomicBoolean wartet = new AtomicBoolean(true);
                job.wartend().incrementAndGet();
                try {
                    schreibSingleton.arbeiten(job, langlaeuferMs, wartet);
                } catch (RuntimeException e) {
                    // ConcurrentAccessTimeoutException nach AccessTimeout (Default Singleton Container: 30 s)
                    Fehlerzaehler.INSTANZ.zaehlen(e);
                    job.fehlgeschlagen();
                    LOG.warning("Langläufer bekam die Sperre nicht: " + e);
                } finally {
                    if (wartet.getAndSet(false)) {
                        job.wartend().decrementAndGet();
                    }
                }
            }
            default -> arbeiten(job, langlaeuferMs);
        }
    }

    /** Die eigentliche Arbeit: hier nur Warten, beim Kunden z. B. die Stammdatenversorgung. */
    static void arbeiten(SchedulerJob job, long ms) {
        long start = job.gestartet(0);
        try {
            Umgebung.schlafen(ms);
        } finally {
            job.beendet(start, true);
        }
    }

    private void blockieren(long ms) {
        SchedulerJob job = SchedulerJob.fuer("ejb", "blockierer", 0);
        long start = job.gestartet(0);
        SzenarioStatus.INSTANZ.timerBlockiert.incrementAndGet();
        try {
            Umgebung.schlafen(ms);
        } finally {
            SzenarioStatus.INSTANZ.timerBlockiert.decrementAndGet();
            job.beendet(start, true);
        }
    }
}
