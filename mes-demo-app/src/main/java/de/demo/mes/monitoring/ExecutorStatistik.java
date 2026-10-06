package de.demo.mes.monitoring;

import java.lang.reflect.Field;
import java.lang.reflect.Method;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.atomic.AtomicLong;
import java.util.logging.Level;
import java.util.logging.Logger;

import de.demo.mes.infra.Executoren;
import de.demo.mes.infra.MBeans;
import jakarta.enterprise.concurrent.ManagedExecutorService;

public final class ExecutorStatistik implements ExecutorStatistikMXBean {

    private static final Logger LOG = Logger.getLogger(ExecutorStatistik.class.getName());
    private static final Map<String, ExecutorStatistik> ALLE = new ConcurrentHashMap<>();

    private final String name;
    private final AtomicLong eingereicht = new AtomicLong();
    private final AtomicLong abgelehnt = new AtomicLong();
    private volatile ManagedExecutorService executor;
    private volatile ThreadPoolExecutor pool;

    private ExecutorStatistik(String name) {
        this.name = name;
    }

    public static void alleRegistrieren() {
        for (String name : Executoren.NAMEN) {
            ExecutorStatistik statistik = fuer(name);
            // JNDI hier auflösen: Der JMX Exporter liest später aus einem Thread ohne Webapp-Kontext.
            statistik.pool();
            MBeans.registrieren(statistik, "type=Executor,name=" + name);
        }
    }

    public static ExecutorStatistik fuer(String name) {
        return ALLE.computeIfAbsent(name, ExecutorStatistik::new);
    }

    public static Map<String, ExecutorStatistik> alle() {
        return ALLE;
    }

    /** Reicht eine Aufgabe ein und zählt Ablehnungen, statt sie zu werfen. */
    public boolean einreichen(Runnable aufgabe) {
        eingereicht.incrementAndGet();
        try {
            executor().execute(aufgabe);
            return true;
        } catch (RejectedExecutionException e) {
            abgelehnt.incrementAndGet();
            return false;
        }
    }

    public ManagedExecutorService executor() {
        if (executor == null) {
            executor = Executoren.holen(name);
        }
        return executor;
    }

    /**
     * Die TomEE-Implementierung (ManagedExecutorServiceImpl) kapselt einen
     * ThreadPoolExecutor. Er wird per Reflection geholt, damit die App nicht
     * gegen openejb-core kompilieren muss.
     */
    private ThreadPoolExecutor pool() {
        if (pool != null || executor == null && !istWebappThread()) {
            return pool;
        }
        try {
            Object ziel = executor();
            Method delegate = findeMethode(ziel.getClass(), "getDelegate");
            if (delegate != null) {
                delegate.setAccessible(true);
                ziel = delegate.invoke(ziel);
            }
            if (ziel instanceof ThreadPoolExecutor tpe) {
                pool = tpe;
            } else if (ziel instanceof ExecutorService) {
                pool = ausFeld(ziel);
            }
        } catch (Exception e) {
            LOG.log(Level.FINE, "Executor " + name + " nicht auslesbar", e);
        }
        return pool;
    }

    private static boolean istWebappThread() {
        return Thread.currentThread().getContextClassLoader() == ExecutorStatistik.class.getClassLoader();
    }

    private static Method findeMethode(Class<?> typ, String name) {
        for (Class<?> c = typ; c != null; c = c.getSuperclass()) {
            for (Method m : c.getDeclaredMethods()) {
                if (m.getName().equals(name) && m.getParameterCount() == 0) {
                    return m;
                }
            }
        }
        return null;
    }

    private static ThreadPoolExecutor ausFeld(Object objekt) throws IllegalAccessException {
        for (Class<?> c = objekt.getClass(); c != null; c = c.getSuperclass()) {
            for (Field f : c.getDeclaredFields()) {
                if (ThreadPoolExecutor.class.isAssignableFrom(f.getType())) {
                    f.setAccessible(true);
                    return (ThreadPoolExecutor) f.get(objekt);
                }
            }
        }
        return null;
    }

    public Map<String, Object> schnappschuss() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("name", name);
        m.put("core", getCorePoolSize());
        m.put("max", getMaximumPoolSize());
        m.put("threads", getPoolSize());
        m.put("aktiv", getActiveCount());
        m.put("queue", getQueueSize());
        m.put("queueFrei", getQueueRemainingCapacity());
        m.put("maxThreadsBisher", getLargestPoolSize());
        m.put("erledigt", getCompletedTaskCount());
        m.put("eingereicht", getEingereicht());
        m.put("abgelehnt", getAbgelehnt());
        return m;
    }

    @Override
    public String getName() {
        return name;
    }

    // Solange eine Lazy-Ressource noch nie benutzt wurde, existiert kein Pool: dann -1.

    @Override
    public int getCorePoolSize() {
        ThreadPoolExecutor p = pool();
        return p == null ? -1 : p.getCorePoolSize();
    }

    @Override
    public int getMaximumPoolSize() {
        ThreadPoolExecutor p = pool();
        return p == null ? -1 : p.getMaximumPoolSize();
    }

    @Override
    public int getPoolSize() {
        ThreadPoolExecutor p = pool();
        return p == null ? -1 : p.getPoolSize();
    }

    @Override
    public int getLargestPoolSize() {
        ThreadPoolExecutor p = pool();
        return p == null ? -1 : p.getLargestPoolSize();
    }

    @Override
    public int getActiveCount() {
        ThreadPoolExecutor p = pool();
        return p == null ? -1 : p.getActiveCount();
    }

    @Override
    public int getQueueSize() {
        ThreadPoolExecutor p = pool();
        return p == null ? -1 : p.getQueue().size();
    }

    @Override
    public int getQueueRemainingCapacity() {
        ThreadPoolExecutor p = pool();
        return p == null ? -1 : p.getQueue().remainingCapacity();
    }

    @Override
    public long getCompletedTaskCount() {
        ThreadPoolExecutor p = pool();
        return p == null ? -1 : p.getCompletedTaskCount();
    }

    @Override
    public long getEingereicht() {
        return eingereicht.get();
    }

    @Override
    public long getAbgelehnt() {
        return abgelehnt.get();
    }
}
