package de.demo.mes.monitoring;

/**
 * Heartbeat eines Scheduler-Jobs. Beantwortet die Kundenfrage „läuft der Timer
 * überhaupt noch?“: Ein ausbleibender Lauf meldet sich nicht selbst, deshalb
 * zählt vor allem {@link #getSekundenSeitLetztemStart()}.
 */
public interface SchedulerJobMXBean {

    String getScheduler();

    String getJob();

    long getSollIntervallSekunden();

    long getLetzterStartEpochSekunden();

    /** Wächst unbegrenzt, wenn der Job nicht mehr feuert – das eigentliche Alarmkriterium. */
    double getSekundenSeitLetztemStart();

    /** Ist-Start minus Soll-Start des letzten Laufs. */
    long getLetzteVerspaetungMs();

    long getMaxVerspaetungMs();

    long getLaeufe();

    long getFehler();

    /** Nur Quartz: Trigger, die ihren Termin um mehr als misfireThreshold verpasst haben. */
    long getMisfires();

    /** Fällige Läufe, die der Überlappungsschutz ausgelassen hat, weil der vorige noch lief (S11). */
    long getUebersprungen();

    long getLetzteLaufzeitMs();

    int getLaeuftGerade();

    /** Fällige Läufe, die auf die Sperre eines Singletons warten – jeder belegt dabei einen Timer-Thread (S11). */
    int getWartend();

    void zuruecksetzen();
}
