package de.demo.mes.monitoring;

import java.util.concurrent.Executors;
import java.util.concurrent.ScheduledExecutorService;
import java.util.concurrent.TimeUnit;
import java.util.logging.Logger;

import de.demo.mes.core.DatenQuellen;
import de.demo.mes.infra.MBeans;
import de.demo.mes.infra.Umgebung;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import jakarta.ejb.ConcurrencyManagement;
import jakarta.ejb.ConcurrencyManagementType;
import jakarta.ejb.Singleton;
import jakarta.ejb.Startup;

/**
 * Registriert die eigenen MBeans und aktualisiert die periodischen Werte.
 * Läuft bewusst in einem eigenen Thread und nicht als EJB-Timer: Die Überwachung
 * darf nicht von dem Pool abhängen, den sie überwachen soll.
 */
@Singleton
@Startup
@ConcurrencyManagement(ConcurrencyManagementType.BEAN)
public class Ueberwachung {

    private static final Logger LOG = Logger.getLogger(Ueberwachung.class.getName());

    private ScheduledExecutorService takt;

    @PostConstruct
    void starten() {
        MBeans.registrieren(Fehlerzaehler.INSTANZ, "type=Fehler");
        MBeans.registrieren(Transaktionen.INSTANZ, "type=Transaktionen");
        MBeans.registrieren(SzenarioStatus.INSTANZ, "type=Szenario");
        ExecutorStatistik.alleRegistrieren();
        JdbcZugriff.fuer(DatenQuellen.MES);
        JdbcZugriff.fuer(DatenQuellen.MASTER);
        // schon vor der ersten Nachricht sichtbar (Grafana zeigt sonst „No data“)
        MdbStatistik.fuer("NachrichtenVerarbeitung");

        boolean oracleUeberwachen = Boolean.parseBoolean(Umgebung.text("MES_ORACLE_MONITOR", "false"));
        if (oracleUeberwachen) {
            MBeans.registrieren(OracleSperren.INSTANZ, "type=OracleSperren");
        }

        takt = Executors.newSingleThreadScheduledExecutor(r -> {
            Thread t = new Thread(r, "mes-ueberwachung");
            t.setDaemon(true);
            return t;
        });
        takt.scheduleWithFixedDelay(() -> {
            try {
                Transaktionen.INSTANZ.langeTransaktionenLoggen();
                if (oracleUeberwachen) {
                    OracleSperren.INSTANZ.aktualisieren();
                }
            } catch (RuntimeException e) {
                LOG.warning("Überwachung: " + e);
            }
        }, 5, 10, TimeUnit.SECONDS);
        LOG.info("MES-Demo gestartet, Rolle=" + Umgebung.rolle() + ", Oracle-Überwachung=" + oracleUeberwachen);
    }

    @PreDestroy
    void stoppen() {
        takt.shutdownNow();
        OracleSperren.INSTANZ.schliessen();
        MBeans.alleAbmelden();
    }
}
