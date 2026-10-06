package de.demo.mes.szenario;

import de.demo.mes.infra.Umgebung;
import jakarta.ejb.Stateless;

/**
 * Stateless Bean im „Default Stateless Container“ (maxSize 50, strictPooling,
 * accessTimeout 30 s). Belegt eine Bean-Instanz, ohne die Datenbank zu brauchen.
 */
@Stateless
public class LangsameBean {

    public long arbeiten(long ms) {
        Umgebung.schlafen(ms);
        return ms;
    }
}
