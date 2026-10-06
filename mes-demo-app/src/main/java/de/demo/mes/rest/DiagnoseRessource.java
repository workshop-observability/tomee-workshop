package de.demo.mes.rest;

import java.lang.management.BufferPoolMXBean;
import java.lang.management.ManagementFactory;
import java.lang.management.MemoryUsage;
import java.lang.management.ThreadInfo;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;
import java.util.regex.Pattern;

import javax.management.Attribute;
import javax.management.MBeanAttributeInfo;
import javax.management.MBeanServer;
import javax.management.ObjectName;
import javax.management.openmbean.CompositeData;

import de.demo.mes.infra.MBeans;
import de.demo.mes.infra.Umgebung;
import de.demo.mes.logging.LogSammler;
import de.demo.mes.monitoring.JdbcZugriff;
import de.demo.mes.monitoring.MdbStatistik;
import de.demo.mes.monitoring.OracleSperren;
import de.demo.mes.monitoring.SzenarioStatus;
import de.demo.mes.monitoring.Transaktionen;
import jakarta.ejb.EJB;
import jakarta.ws.rs.DefaultValue;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;

/**
 * Lesende Diagnose. Liest dieselben MBeans wie JConsole und der JMX Exporter –
 * die Antworten nennen deshalb immer den ObjectName mit.
 */
@Path("diagnose")
@Produces(MediaType.APPLICATION_JSON)
public class DiagnoseRessource {

    private static final Pattern THREAD_NUMMER = Pattern.compile("[-_#]?\\d+$");

    @EJB
    private LogSammler logSammler;

    /** Kompakte Ampel über alle Ebenen der Kausalkette. */
    @GET
    @Path("uebersicht")
    public Map<String, Object> uebersicht() throws Exception {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("rolle", Umgebung.rolle());
        m.put("http", mbeans("Catalina:type=ThreadPool,name=*",
                "currentThreadsBusy", "currentThreadCount", "maxThreads", "connectionCount", "maxConnections"));
        m.put("httpExecutor", mbeans("Catalina:type=Executor,*", "activeCount", "maxThreads", "queueSize", "poolSize"));
        m.put("jdbcPool", mbeans(TomeeMBeans.DATASOURCE, TomeeMBeans.DATASOURCE_ATTRIBUTE));
        List<Map<String, Object>> jdbc = new ArrayList<>();
        JdbcZugriff.alle().values().forEach(z -> jdbc.add(z.schnappschuss()));
        m.put("jdbcAnwendungssicht", jdbc);
        m.put("beanPools", mbeans(TomeeMBeans.BEAN_POOL, TomeeMBeans.BEAN_POOL_ATTRIBUTE));
        m.put("executoren", mbeans(TomeeMBeans.EXECUTOR, TomeeMBeans.EXECUTOR_ATTRIBUTE));
        m.put("scheduler", mbeans(MBeans.DOMAIN + ":type=SchedulerJob,*",
                "SekundenSeitLetztemStart", "LaeuftGerade", "MaxVerspaetungMs", "Misfires", "Wartend",
                "Uebersprungen", "Fehler", "Laeufe"));
        m.put("transaktionen", Map.of("aktiv", Transaktionen.INSTANZ.getAktive(),
                "aeltesteSekunden", Transaktionen.INSTANZ.getAeltesteSekunden(),
                "liste", Transaktionen.INSTANZ.liste()));
        m.put("mdb", mbeans(TomeeMBeans.MDB, TomeeMBeans.MDB_ATTRIBUTE));
        List<Map<String, Object>> mdb = new ArrayList<>();
        MdbStatistik.alle().forEach((name, st) -> {
            Map<String, Object> z = new LinkedHashMap<>();
            z.put("mdb", name);
            z.put("aktiv", st.getAktiv());
            z.put("verarbeitet", st.getVerarbeitet());
            z.put("fehler", st.getFehler());
            z.put("wartezeitSekunden", Math.round(st.getLetzteWartezeitSekunden() * 10) / 10.0);
            mdb.add(z);
        });
        m.put("mdbAnwendungssicht", mdb);
        m.put("logSammler", logSammler.zustand());
        m.put("wartung", SzenarioStatus.INSTANZ.inWartung());
        m.put("fehler", mbeans(MBeans.DOMAIN + ":type=Fehler"));
        m.put("szenario", mbeans(MBeans.DOMAIN + ":type=Szenario"));
        m.put("jvm", jvm());
        return m;
    }

    @GET
    @Path("db-sperren")
    public Map<String, Object> dbSperren() throws Exception {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("abfrage", "V$SESSION.BLOCKING_SESSION, V$LOCKED_OBJECT (User MES_MONITOR)");
        m.put("blockierketten", OracleSperren.abfragen(OracleSperren.SQL_BLOCKIERKETTEN));
        m.put("gesperrteObjekte", OracleSperren.abfragen(OracleSperren.SQL_GESPERRTE_OBJEKTE));
        return m;
    }

    /** Threads nach Zustand und nach Namensgruppe – der schnellste Weg zu „wer hängt woran?“. */
    @GET
    @Path("threads")
    public Map<String, Object> threads(@QueryParam("gruppe") String gruppe,
                                       @QueryParam("stack") @DefaultValue("8") int stackTiefe) {
        ThreadInfo[] infos = ManagementFactory.getThreadMXBean().dumpAllThreads(false, false, stackTiefe);
        Map<String, Integer> zustaende = new TreeMap<>();
        Map<String, Map<String, Integer>> gruppen = new TreeMap<>();
        List<Map<String, Object>> details = new ArrayList<>();
        for (ThreadInfo info : infos) {
            String name = THREAD_NUMMER.matcher(info.getThreadName()).replaceAll("");
            String zustand = info.getThreadState().name();
            zustaende.merge(zustand, 1, Integer::sum);
            gruppen.computeIfAbsent(name, k -> new TreeMap<>()).merge(zustand, 1, Integer::sum);
            if (gruppe != null && info.getThreadName().contains(gruppe) && details.size() < 20) {
                Map<String, Object> d = new LinkedHashMap<>();
                d.put("name", info.getThreadName());
                d.put("zustand", zustand);
                d.put("wartetAuf", info.getLockName());
                List<String> stack = new ArrayList<>();
                for (StackTraceElement e : info.getStackTrace()) {
                    stack.add(e.toString());
                }
                d.put("stack", stack);
                details.add(d);
            }
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("gesamt", infos.length);
        m.put("nachZustand", zustaende);
        m.put("nachGruppe", gruppen);
        if (gruppe != null) {
            m.put("details", details);
        }
        return m;
    }

    /** MBean-Inventur: {@code ?muster=Catalina:type=ThreadPool,*} */
    @GET
    @Path("mbeans")
    public Map<String, Object> mbeanInventur(@QueryParam("muster") @DefaultValue("*:*") String muster,
                                             @QueryParam("attribute") @DefaultValue("false") boolean attribute)
            throws Exception {
        MBeanServer server = MBeans.server();
        Map<String, Object> m = new TreeMap<>();
        for (ObjectName name : server.queryNames(new ObjectName(muster), null)) {
            m.put(name.toString(), attribute ? attributeLesen(server, name, null) : "");
        }
        return m;
    }

    @GET
    @Path("konfig")
    public Map<String, Object> konfig() throws Exception {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("rolle", Umgebung.rolle());
        m.put("konfig", Umgebung.text("KONFIG", "?"));
        m.put("jvmArgumente", ManagementFactory.getRuntimeMXBean().getInputArguments());
        m.put("javaVersion", System.getProperty("java.version"));
        m.put("prozessoren", Runtime.getRuntime().availableProcessors());
        m.put("heapMaxMb", Runtime.getRuntime().maxMemory() / 1024 / 1024);
        m.put("containerLimitMb", containerLimitMb());
        m.put("openejb.timer.pool.size", System.getProperty("openejb.timer.pool.size", "3 (Default)"));
        Map<String, Object> tx = new LinkedHashMap<>();
        tx.put("effektivSekunden (Geronimo)", effektiverTransaktionsTimeout());
        tx.put("jmx", mbeans(TomeeMBeans.TRANSAKTIONSMANAGER));
        m.put("transaktionsTimeout", tx);
        m.put("dataSources", mbeans(TomeeMBeans.DATASOURCE, TomeeMBeans.DATASOURCE_KONFIG));
        m.put("beanPools", mbeans(TomeeMBeans.BEAN_POOL, "MaxSize", "MinSize", "StrictPooling", "IdleTimeout"));
        m.put("connectoren", mbeans("Catalina:type=ProtocolHandler,port=*",
                "maxThreads", "maxConnections", "acceptCount", "connectionTimeout", "keepAliveTimeout"));
        return m;
    }

    /**
     * Liest den tatsächlich verwendeten Default-Timeout aus dem Geronimo-TransactionManager.
     * Die TomEE-MBean zeigt dagegen nur die Duration-Eigenschaft (Default 10 Minuten).
     */
    private static Object effektiverTransaktionsTimeout() {
        try {
            Object tm = new javax.naming.InitialContext().lookup("java:comp/TransactionManager");
            for (int tiefe = 0; tm != null && tiefe < 4; tiefe++) {
                Object wert = feld(tm, "defaultTransactionTimeoutMilliseconds");
                if (wert instanceof Number ms) {
                    return ms.longValue() / 1000;
                }
                tm = feldVomTyp(tm, jakarta.transaction.TransactionManager.class);
            }
            return "nicht ermittelbar";
        } catch (Exception e) {
            return "nicht ermittelbar: " + e;
        }
    }

    private static Object feld(Object objekt, String name) throws IllegalAccessException {
        for (Class<?> c = objekt.getClass(); c != null; c = c.getSuperclass()) {
            for (java.lang.reflect.Field f : c.getDeclaredFields()) {
                if (f.getName().equals(name)) {
                    f.setAccessible(true);
                    return f.get(objekt);
                }
            }
        }
        return null;
    }

    private static Object feldVomTyp(Object objekt, Class<?> typ) throws IllegalAccessException {
        for (Class<?> c = objekt.getClass(); c != null; c = c.getSuperclass()) {
            for (java.lang.reflect.Field f : c.getDeclaredFields()) {
                if (typ.isAssignableFrom(f.getType())) {
                    f.setAccessible(true);
                    return f.get(objekt);
                }
            }
        }
        return null;
    }

    private static Object containerLimitMb() {
        try {
            String wert = Files.readString(java.nio.file.Path.of("/sys/fs/cgroup/memory.max")).trim();
            return "max".equals(wert) ? "unbegrenzt" : Long.parseLong(wert) / 1024 / 1024;
        } catch (Exception e) {
            return "unbekannt";
        }
    }

    private static Map<String, Object> jvm() {
        Map<String, Object> m = new LinkedHashMap<>();
        MemoryUsage heap = ManagementFactory.getMemoryMXBean().getHeapMemoryUsage();
        m.put("heapBenutztMb", heap.getUsed() / 1024 / 1024);
        m.put("heapMaxMb", heap.getMax() / 1024 / 1024);
        m.put("threads", ManagementFactory.getThreadMXBean().getThreadCount());
        ManagementFactory.getPlatformMXBeans(BufferPoolMXBean.class).stream()
                .filter(b -> "direct".equals(b.getName()))
                .findFirst()
                .ifPresent(b -> m.put("directBufferMb", b.getMemoryUsed() / 1024 / 1024));
        // Java 21 ist container-bewusst: Total = Container-Limit, Free = Limit − Belegung (cgroup)
        if (ManagementFactory.getOperatingSystemMXBean() instanceof com.sun.management.OperatingSystemMXBean os) {
            m.put("containerBelegtMb", (os.getTotalMemorySize() - os.getFreeMemorySize()) / 1024 / 1024);
            m.put("containerLimitMb", os.getTotalMemorySize() / 1024 / 1024);
        }
        try {
            MBeanServer server = MBeans.server();
            ObjectName os = new ObjectName("java.lang:type=OperatingSystem");
            m.put("offeneFileDescriptors", server.getAttribute(os, "OpenFileDescriptorCount"));
            m.put("maxFileDescriptors", server.getAttribute(os, "MaxFileDescriptorCount"));
        } catch (Exception e) {
            m.put("fileDescriptors", "nicht verfügbar");
        }
        return m;
    }

    private static Map<String, Object> mbeans(String muster, String... attribute) throws Exception {
        MBeanServer server = MBeans.server();
        Map<String, Object> m = new TreeMap<>();
        for (ObjectName name : server.queryNames(new ObjectName(muster), null)) {
            Map<String, Object> werte = attributeLesen(server, name, attribute.length == 0 ? null : attribute);
            if (!werte.isEmpty()) {
                m.put(name.toString(), werte);
            }
        }
        return m;
    }

    private static Map<String, Object> attributeLesen(MBeanServer server, ObjectName name, String[] auswahl)
            throws Exception {
        if (auswahl == null) {
            List<String> alle = new ArrayList<>();
            for (MBeanAttributeInfo info : server.getMBeanInfo(name).getAttributes()) {
                if (info.isReadable()) {
                    alle.add(info.getName());
                }
            }
            auswahl = alle.toArray(String[]::new);
        }
        Map<String, Object> werte = new LinkedHashMap<>();
        for (Attribute a : server.getAttributes(name, auswahl).asList()) {
            Object wert = a.getValue();
            if (wert instanceof CompositeData cd) {
                Map<String, Object> teil = new LinkedHashMap<>();
                cd.getCompositeType().keySet().forEach(k -> teil.put(k, String.valueOf(cd.get(k))));
                wert = teil;
            } else if (wert != null && !(wert instanceof Number) && !(wert instanceof Boolean)) {
                wert = String.valueOf(wert);
            }
            werte.put(a.getName(), wert);
        }
        return werte;
    }
}
