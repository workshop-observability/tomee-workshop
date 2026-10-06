package de.demo.mes.scheduler;

import java.util.concurrent.atomic.AtomicBoolean;

import de.demo.mes.monitoring.SchedulerJob;
import jakarta.ejb.Singleton;

/**
 * Ein {@code @Singleton} ohne weitere Annotation – so sieht ein Scheduler-Bean häufig aus.
 * Container-Managed Concurrency mit dem Default {@code @Lock(WRITE)}: Es arbeitet immer nur
 * ein Aufrufer, alle anderen warten auf die Sperre, höchstens {@code AccessTimeout}
 * (Default Singleton Container: 30 s), dann {@code ConcurrentAccessTimeoutException}.
 */
@Singleton
public class SchreibSingleton {

    /** @param wartet wird auf false gesetzt, sobald die Sperre vergeben ist */
    public void arbeiten(SchedulerJob job, long ms, AtomicBoolean wartet) {
        if (wartet.getAndSet(false)) {
            job.wartend().decrementAndGet();
        }
        EjbZeitplaene.arbeiten(job, ms);
    }
}
