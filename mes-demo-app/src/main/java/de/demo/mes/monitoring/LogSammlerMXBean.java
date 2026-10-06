package de.demo.mes.monitoring;

/**
 * Log-Sammler nach dem Muster des Kunden: Anwendung → Singleton → Queue → einmal pro
 * Sekunde in eine Textdatei. Zeigt, ob die Queue mit dem Schreiben mithält (S16, S17).
 */
public interface LogSammlerMXBean {

    /** unbegrenzt | verwerfen | blockieren */
    String getModus();

    /** Einträge, die auf das Schreiben warten. */
    int getQueueTiefe();

    /** Obergrenze der Queue; -1 = unbegrenzt. */
    int getQueueKapazitaet();

    /** Alter des ältesten noch nicht geschriebenen Eintrags – der Log-Verzug. */
    double getAeltesterEintragSekunden();

    /** Aufrufer, die gerade auf einen freien Platz in der Queue warten (Modus blockieren). */
    int getWartendeAufrufer();

    /** Wie viele Zeilen der Schreiber höchstens pro Sekunde schafft; 0 = ohne Grenze. */
    int getSchreibLimitProSekunde();

    long getAngenommen();

    long getGeschrieben();

    /** Nicht angenommen, weil die Queue voll war (Modus verwerfen). */
    long getVerworfen();

    long getLetzteSchreibdauerMs();
}
