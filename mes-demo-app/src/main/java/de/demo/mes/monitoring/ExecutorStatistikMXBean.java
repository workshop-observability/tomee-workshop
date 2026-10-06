package de.demo.mes.monitoring;

/**
 * Auslastung eines ManagedExecutorService aus tomee.xml. TomEE selbst
 * veröffentlicht diese Werte nicht als MBean, deshalb liest die Demo sie hier aus.
 */
public interface ExecutorStatistikMXBean {

    String getName();

    int getCorePoolSize();

    int getMaximumPoolSize();

    /** Existierende Threads. Liegt nur über Core, wenn die Queue voll ist. */
    int getPoolSize();

    int getLargestPoolSize();

    int getActiveCount();

    int getQueueSize();

    int getQueueRemainingCapacity();

    long getCompletedTaskCount();

    /** Von der Demo eingereichte Aufgaben. */
    long getEingereicht();

    /** RejectedExecutionException: Queue voll und Max erreicht. */
    long getAbgelehnt();
}
