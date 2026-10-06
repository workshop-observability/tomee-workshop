package de.demo.mes.monitoring;

/**
 * Zählt Fehler nach Ursache. Zeigt den Kern der Tuning-Empfehlung: Ein endliches
 * Timeout verwandelt ein stummes Hängen in einen zählbaren Fehler.
 */
public interface FehlerzaehlerMXBean {

    /** JDBC-Pool leer und maxWaitTime abgelaufen. */
    long getPoolErschoepft();

    /** Stateless-Bean-Pool leer und accessTimeout abgelaufen. */
    long getBeanPoolTimeout();

    /** Singleton-Lock nicht rechtzeitig bekommen. */
    long getSingletonTimeout();

    /** ORA-30006/ORA-00054: Zeile/Tabelle gesperrt, WAIT/NOWAIT abgelaufen. */
    long getSperrTimeout();

    /** Query-Timeout oder oracle.jdbc.ReadTimeout. */
    long getAbfrageTimeout();

    /** Transaktion wegen Timeout oder setRollbackOnly zurückgerollt. */
    long getTransaktionAbgebrochen();

    long getExecutorAbgelehnt();

    /** Client hat die Verbindung vor der Antwort getrennt (z. B. HAProxy-Timeout, Lasttest beendet). */
    long getClientAbbruch();

    /** Oracle hat die Anmeldung abgelehnt: Sitzungs- oder Prozessgrenze der DB erreicht (S15). */
    long getDbSitzungslimit();

    long getSonstige();
}
