package de.demo.mes.rest;

/** ObjectName-Muster der TomEE-eigenen MBeans (am laufenden TomEE Plume 10.1.2 ermittelt). */
final class TomeeMBeans {

    /** Ohne ",connections=…": das sind die Einzel-MBeans je gepoolter Connection. */
    static final String DATASOURCE = "openejb.management:ObjectType=datasources,DataSource=*";
    static final String[] DATASOURCE_ATTRIBUTE = {"Active", "Idle", "Size", "WaitCount", "MaxActive",
            "BorrowedCount", "RemoveAbandonedCount"};
    static final String[] DATASOURCE_KONFIG = {"MaxActive", "MaxIdle", "MinIdle", "InitialSize", "MaxWait",
            "RemoveAbandoned", "RemoveAbandonedTimeout", "LogAbandoned", "SuspectTimeout",
            "TimeBetweenEvictionRunsMillis", "TestOnBorrow", "TestWhileIdle", "ConnectionProperties"};

    static final String BEAN_POOL = "openejb.management:j2eeType=Pool,*";
    static final String[] BEAN_POOL_ATTRIBUTE = {"InstancesActive", "InstancesIdle", "AvailablePermits",
            "MaxSize", "AccessTimeouts"};

    static final String EXECUTOR = "openejb.management:j2eeType=Resource,*";
    static final String[] EXECUTOR_ATTRIBUTE = {"corePoolSize", "maximumPoolSize", "poolSize", "activeCount",
            "queueSize", "largestPoolSize"};

    static final String TRANSAKTIONSMANAGER = "openejb.management:j2eeType=TransactionManager";

    /** Alle MBeans einer Message-Driven Bean (Instanzen, Aufrufe, Start/Stopp-Steuerung). */
    static final String MDB = "openejb.management:MessageDrivenBean=*,*";
    static final String[] MDB_ATTRIBUTE = {"InstanceCount", "InstanceLimit", "started"};

    private TomeeMBeans() {
    }
}
