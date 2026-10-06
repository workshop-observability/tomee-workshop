package de.demo.mes.monitoring;

/** DB-seitige Sicht auf die Verbindungen eines Users – Gegenprobe zur Pool-MBean. */
public interface OracleSitzungenMXBean {

    String getBenutzer();

    int getGesamt();

    /** Session führt gerade ein Statement aus (oder wartet darin). */
    int getAktiv();

    int getInaktiv();

    int getBlockiert();

    /** SESSIONS_PER_USER aus dem Profil des Users; -1 = unbegrenzt. Darüber: ORA-02391 (S15). */
    int getLimit();
}
