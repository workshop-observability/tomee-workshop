package de.demo.mes.scheduler;

import static org.quartz.CronScheduleBuilder.cronSchedule;
import static org.quartz.JobBuilder.newJob;
import static org.quartz.TriggerBuilder.newTrigger;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Properties;
import java.util.UUID;
import java.util.logging.Logger;

import org.quartz.Job;
import org.quartz.JobExecutionContext;
import org.quartz.JobExecutionException;
import org.quartz.Scheduler;
import org.quartz.SchedulerException;
import org.quartz.Trigger;
import org.quartz.impl.StdSchedulerFactory;
import org.quartz.listeners.TriggerListenerSupport;

import de.demo.mes.core.StammdatenService;
import de.demo.mes.infra.Umgebung;
import de.demo.mes.monitoring.Fehlerzaehler;
import de.demo.mes.monitoring.SchedulerJob;
import de.demo.mes.monitoring.SzenarioStatus;
import jakarta.annotation.PostConstruct;
import jakarta.annotation.PreDestroy;
import jakarta.ejb.ConcurrencyManagement;
import jakarta.ejb.ConcurrencyManagementType;
import jakarta.ejb.EJB;
import jakarta.ejb.Singleton;
import jakarta.ejb.Startup;

/**
 * Eigenständiger Quartz-Scheduler, wie ihn eine Anwendung selbst mitbringt.
 * Exportiert seine JMX-MBean unter {@code quartz:type=QuartzScheduler,name=MesQuartz,…}.
 */
@Singleton
@Startup
@ConcurrencyManagement(ConcurrencyManagementType.BEAN)
public class QuartzZeitplaene {

    private static final Logger LOG = Logger.getLogger(QuartzZeitplaene.class.getName());
    private static final String STAMMDATEN = "stammdaten";

    @EJB
    private StammdatenService stammdaten;

    private Scheduler scheduler;

    @PostConstruct
    void starten() throws SchedulerException {
        Properties p = new Properties();
        p.setProperty("org.quartz.scheduler.instanceName", "MesQuartz");
        p.setProperty("org.quartz.scheduler.skipUpdateCheck", "true");
        p.setProperty("org.quartz.scheduler.jmx.export", "true");
        p.setProperty("org.quartz.threadPool.class", "org.quartz.simpl.SimpleThreadPool");
        p.setProperty("org.quartz.threadPool.threadCount", Umgebung.text("QUARTZ_THREADS", "5"));
        p.setProperty("org.quartz.threadPool.threadNamePrefix", "MesQuartz_Worker");
        p.setProperty("org.quartz.jobStore.class", "org.quartz.simpl.RAMJobStore");
        p.setProperty("org.quartz.jobStore.misfireThreshold", Umgebung.text("QUARTZ_MISFIRE_MS", "60000"));

        scheduler = new StdSchedulerFactory(p).getScheduler();
        scheduler.getContext().put(STAMMDATEN, stammdaten);
        scheduler.getListenerManager().addTriggerListener(new MisfireZaehler());

        SchedulerJob.fuer("quartz", "heartbeat", 10);
        SchedulerJob.fuer("quartz", "stammdatenabgleich", 60);
        planen(HeartbeatJob.class, "heartbeat", "*/10 * * * * ?");
        planen(AbgleichJob.class, "stammdatenabgleich", "0 * * * * ?");
        scheduler.start();
    }

    private void planen(Class<? extends Job> typ, String name, String cron) throws SchedulerException {
        scheduler.scheduleJob(
                newJob(typ).withIdentity(name).build(),
                newTrigger().withIdentity(name).withSchedule(cronSchedule(cron)).build());
    }

    public void blockierenEinplanen(int anzahl, long ms) throws SchedulerException {
        for (int i = 0; i < anzahl; i++) {
            String id = "blockierer-" + UUID.randomUUID();
            scheduler.scheduleJob(
                    newJob(BlockiererJob.class).withIdentity(id).usingJobData("ms", ms).build(),
                    newTrigger().withIdentity(id).startNow().build());
        }
    }

    public Map<String, Object> status() throws SchedulerException {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("threads", scheduler.getMetaData().getThreadPoolSize());
        m.put("laufendeJobs", scheduler.getCurrentlyExecutingJobs().size());
        m.put("ausgefuehrtSeitStart", scheduler.getMetaData().getNumberOfJobsExecuted());
        return m;
    }

    @PreDestroy
    void stoppen() throws SchedulerException {
        scheduler.shutdown(false);
    }

    private static void messen(JobExecutionContext ctx, String job, Runnable arbeit) {
        SchedulerJob statistik = SchedulerJob.fuer("quartz", job, 0);
        long start = statistik.gestartet(ctx.getScheduledFireTime().getTime());
        boolean erfolgreich = false;
        try {
            arbeit.run();
            erfolgreich = true;
        } catch (RuntimeException e) {
            Fehlerzaehler.INSTANZ.zaehlen(e);
            LOG.warning("Quartz-Job " + job + " fehlgeschlagen: " + e);
        } finally {
            statistik.beendet(start, erfolgreich);
        }
    }

    public static class HeartbeatJob implements Job {
        @Override
        public void execute(JobExecutionContext ctx) {
            messen(ctx, "heartbeat", () -> { });
        }
    }

    public static class AbgleichJob implements Job {
        @Override
        public void execute(JobExecutionContext ctx) throws JobExecutionException {
            StammdatenService service;
            try {
                service = (StammdatenService) ctx.getScheduler().getContext().get(STAMMDATEN);
            } catch (SchedulerException e) {
                throw new JobExecutionException(e);
            }
            messen(ctx, "stammdatenabgleich", () -> {
                try {
                    service.abgleichen();
                } catch (Exception e) {
                    throw new IllegalStateException(e);
                }
            });
        }
    }

    public static class BlockiererJob implements Job {
        @Override
        public void execute(JobExecutionContext ctx) {
            long ms = ctx.getMergedJobDataMap().getLong("ms");
            messen(ctx, "blockierer", () -> {
                SzenarioStatus.INSTANZ.timerBlockiert.incrementAndGet();
                try {
                    Umgebung.schlafen(ms);
                } finally {
                    SzenarioStatus.INSTANZ.timerBlockiert.decrementAndGet();
                }
            });
        }
    }

    /** Quartz meldet verpasste Termine erst, wenn wieder ein Thread frei ist. */
    private static final class MisfireZaehler extends TriggerListenerSupport {
        @Override
        public String getName() {
            return "mes-misfire-zaehler";
        }

        @Override
        public void triggerMisfired(Trigger trigger) {
            SchedulerJob.fuer("quartz", trigger.getJobKey().getName().replaceAll("-.*", ""), 0).misfire();
        }
    }
}
