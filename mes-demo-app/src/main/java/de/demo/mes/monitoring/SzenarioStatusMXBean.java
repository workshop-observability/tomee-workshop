package de.demo.mes.monitoring;

/**
 * Welche Störung ist gerade absichtlich aktiv? Dient in Grafana als Markierung,
 * damit Ursache und Wirkung nebeneinander sichtbar sind.
 */
public interface SzenarioStatusMXBean {

    int getGehalteneSperren();

    long getGehaltenerHeapMb();

    int getOffeneDateien();

    int getBlockierteTimerThreads();

    int getLaufendeLangeTransaktionen();

    /** 1 = Applikationsserver im Wartungsmodus: /mes/api/status antwortet 503, HAProxy nimmt ihn heraus (S13). */
    int getWartung();

    /** Direct Buffer außerhalb des Heaps (S14). */
    long getGehaltenerOffHeapMb();

    /** Zusätzlich gestartete, schlafende Threads mit belegtem Stack (S14). */
    int getZusaetzlicheThreads();

    /** Ausgeliehene und nie zurückgegebene Connections (S18). */
    int getGeleckteConnections();
}
