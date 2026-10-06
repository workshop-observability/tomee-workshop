package de.demo.mes.core;

import java.sql.Connection;
import java.sql.SQLClientInfoException;
import java.sql.SQLException;
import java.util.List;

import javax.naming.InitialContext;
import javax.naming.NamingException;
import javax.sql.DataSource;

import de.demo.mes.infra.Umgebung;
import de.demo.mes.monitoring.JdbcZugriff;

/** Die beiden DataSources aus tomee.xml, gemessen über {@link JdbcZugriff}. */
public final class DatenQuellen {

    public static final String MES = "MES_Connection";
    public static final String MASTER = "Master_MES_Connection";
    public static final List<String> NAMEN = List.of(MES, MASTER);

    private DatenQuellen() {
    }

    public static DataSource holen(String name) {
        if (!NAMEN.contains(name)) {
            throw new IllegalArgumentException("Unbekannte DataSource: " + name + " – erlaubt: " + NAMEN);
        }
        try {
            return (DataSource) new InitialContext().lookup("openejb:Resource/" + name);
        } catch (NamingException e) {
            throw new IllegalStateException("DataSource " + name + " nicht gefunden", e);
        }
    }

    /**
     * Leiht eine Connection aus und setzt MODULE/ACTION, damit die Session in
     * V$SESSION einer Rolle und einem Anwendungsfall zugeordnet werden kann.
     */
    public static Connection verbinden(String name, String aktion) throws SQLException {
        Connection c = JdbcZugriff.fuer(name).holen(holen(name), aktion);
        try {
            c.setClientInfo("OCSID.MODULE", "MES-" + Umgebung.rolle());
            c.setClientInfo("OCSID.ACTION", aktion);
        } catch (SQLClientInfoException ignoriert) {
            // nur Komfort für die DB-Diagnose
        } catch (SQLException | RuntimeException e) {
            c.close();
            throw e;
        }
        return c;
    }
}
