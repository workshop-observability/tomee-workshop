package de.demo.mes.infra;

import java.lang.management.ManagementFactory;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;
import java.util.logging.Level;
import java.util.logging.Logger;

import javax.management.MBeanServer;
import javax.management.ObjectName;

/**
 * Registriert die eigenen MBeans im Platform-MBeanServer. Dort liest sie auch der
 * JMX Exporter (Java-Agent) und JConsole. Alle Namen liegen in der Domain {@value #DOMAIN}.
 */
public final class MBeans {

    public static final String DOMAIN = "mes.demo";

    private static final Logger LOG = Logger.getLogger(MBeans.class.getName());
    private static final Set<ObjectName> REGISTRIERT = ConcurrentHashMap.newKeySet();

    private MBeans() {
    }

    public static MBeanServer server() {
        return ManagementFactory.getPlatformMBeanServer();
    }

    /** @param eigenschaften z. B. {@code type=SchedulerJob,scheduler=ejb,job=heartbeat} */
    public static void registrieren(Object mbean, String eigenschaften) {
        try {
            ObjectName name = new ObjectName(DOMAIN + ":" + eigenschaften);
            if (server().isRegistered(name)) {
                server().unregisterMBean(name);
            }
            server().registerMBean(mbean, name);
            REGISTRIERT.add(name);
        } catch (Exception e) {
            LOG.log(Level.WARNING, "MBean " + eigenschaften + " nicht registriert", e);
        }
    }

    public static void alleAbmelden() {
        for (ObjectName name : REGISTRIERT) {
            try {
                if (server().isRegistered(name)) {
                    server().unregisterMBean(name);
                }
            } catch (Exception e) {
                LOG.log(Level.FINE, "Abmelden fehlgeschlagen: " + name, e);
            }
        }
        REGISTRIERT.clear();
    }
}
