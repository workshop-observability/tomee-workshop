package de.demo.mes.monitoring;

/**
 * JTA-Transaktionen der Anwendung. Kundenwunsch: „Transaction Timeouts loggen –
 * länger als eine Stunde ist eh ein Problem“.
 */
public interface TransaktionenMXBean {

    int getAktive();

    double getAeltesteSekunden();

    /** Aktive Transaktionen, die älter als {@link #getWarnSchwelleSekunden()} sind. */
    int getUeberSchwelle();

    long getWarnSchwelleSekunden();

    long getCommits();

    long getRollbacks();
}
