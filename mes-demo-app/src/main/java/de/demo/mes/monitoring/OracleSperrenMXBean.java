package de.demo.mes.monitoring;

/**
 * Datenbanksicht auf Sperren – die Antwort auf „Tabelle war gelocked, wie kann man
 * das vernünftig monitoren?“. Wird über eine eigene Verbindung (User MES_MONITOR)
 * gelesen, damit sie auch dann funktioniert, wenn der Anwendungs-Pool leer ist.
 */
public interface OracleSperrenMXBean {

    /** 1 = letzte Abfrage erfolgreich. */
    int getVerfuegbar();

    /** Sessions, die auf eine Sperre einer anderen Session warten. */
    int getBlockierteSessions();

    /** Sessions, die andere blockieren (Wurzeln der Blockierketten). */
    int getBlockierendeSessions();

    /** Längste aktuelle Wartezeit auf eine Sperre. */
    double getLaengsteWartezeitSekunden();

    /** Anzahl der Objekte (Tabellen) mit DML-Sperren. */
    int getGesperrteObjekte();

    /** Alter der ältesten offenen DB-Transaktion. */
    double getAeltesteTransaktionSekunden();

    long getAbfrageDauerMs();

    /** Serverprozesse der Datenbank (V$PROCESS, inkl. Hintergrundprozesse) – jede Verbindung braucht einen. */
    int getDbProzesse();

    /** Parameter PROCESSES. Darüber: ORA-00020 bzw. ORA-12516 für jede neue Verbindung. */
    int getDbProzesseLimit();

    /** Sessions der Datenbank (V$SESSION). */
    int getDbSitzungen();

    /** Parameter SESSIONS. */
    int getDbSitzungenLimit();
}
