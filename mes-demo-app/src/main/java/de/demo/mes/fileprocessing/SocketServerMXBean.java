package de.demo.mes.fileprocessing;

/** TCP-Schnittstelle des FileProcessing (beim Kunden Ports 50000–50100). */
public interface SocketServerMXBean {

    int getPort();

    /** Jede offene Verbindung belegt einen File Descriptor und einen SocketHandler-Thread. */
    int getOffeneVerbindungen();

    long getAngenommen();

    /** SocketHandler-Pool und -Queue voll: Verbindung wurde sofort geschlossen. */
    long getAbgelehnt();

    /** Angenommen, aber noch kein Thread frei (liegt in der Executor-Queue). */
    int getWartendeVerbindungen();

    long getDateien();

    long getBytes();

    long getVerarbeitungsFehler();
}
