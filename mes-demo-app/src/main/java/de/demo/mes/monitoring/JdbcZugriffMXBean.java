package de.demo.mes.monitoring;

/**
 * Anwendungssicht auf einen JDBC-Pool. Ergänzt die Pool-MBean von TomEE um die
 * beiden Werte, die ein Lock am frühesten verraten: Wartezeit beim Ausleihen
 * und Alter der ältesten ausgeliehenen Connection.
 */
public interface JdbcZugriffMXBean {

    String getDataSource();

    /** Threads, die gerade in getConnection() stecken. */
    int getWartendeThreads();

    /** Aktuell von der Anwendung gehaltene Connections. */
    int getAusgelieheneConnections();

    /** Alter der am längsten gehaltenen Connection – ein Lock zeigt sich hier als stetig wachsender Wert. */
    double getAeltesteAusleiheSekunden();

    long getAusleihen();

    long getAusleihFehler();

    /** Summe aller Wartezeiten (Counter) – rate(Summe)/rate(Ausleihen) = mittlere Wartezeit. */
    long getWartezeitMsSumme();

    long getLetzteWartezeitMs();

    /** Maximum der letzten 60 Sekunden. */
    long getMaxWartezeitMs();

    /** Längste Wartezeit eines Threads, der noch wartet. */
    double getLaengsteAktuelleWartezeitSekunden();
}
