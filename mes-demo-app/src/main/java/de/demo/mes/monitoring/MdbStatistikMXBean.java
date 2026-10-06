package de.demo.mes.monitoring;

/**
 * Verarbeitung einer Message-Driven Bean aus Sicht der Anwendung (S12). Ergänzt die
 * TomEE-MBean (Instanzen) und die Broker-Sicht (Queue-Tiefe): Wie lange hat eine
 * Nachricht in der Queue gelegen, bevor sie drankam?
 */
public interface MdbStatistikMXBean {

    String getMdb();

    /** Nachrichten, die gerade verarbeitet werden – höchstens InstanceLimit bzw. maxSessions (Default je 10). */
    int getAktiv();

    long getVerarbeitet();

    /** onMessage mit Exception beendet – der Broker stellt die Nachricht erneut zu. */
    long getFehler();

    /** Zustellungen mit JMSRedelivered = true: Wiederholungen nach einem Fehler. */
    long getWiederholungen();

    /** Zeit zwischen Senden und Verarbeitungsbeginn der zuletzt begonnenen Nachricht. */
    double getLetzteWartezeitSekunden();

    /** Größte Wartezeit in der Queue innerhalb der letzten 60 s. */
    double getMaxWartezeitSekunden();

    long getLetzteLaufzeitMs();
}
