package de.demo.mes.infra;

import java.util.List;

import javax.naming.InitialContext;
import javax.naming.NamingException;

import jakarta.enterprise.concurrent.ManagedExecutorService;

/** Zugriff auf die ManagedExecutorServices aus tomee.xml. */
public final class Executoren {

    /** Reihenfolge und Namen exakt wie in der tomee.xml des Kunden. */
    public static final List<String> NAMEN =
            List.of("GeneralThreadPool", "FileWatcher", "SocketHandler", "MslHandling", "BatchHandling");

    private Executoren() {
    }

    public static ManagedExecutorService holen(String name) {
        if (!NAMEN.contains(name)) {
            throw new IllegalArgumentException("Unbekannter Executor: " + name + " – erlaubt: " + NAMEN);
        }
        try {
            return (ManagedExecutorService) new InitialContext().lookup("openejb:Resource/" + name);
        } catch (NamingException e) {
            throw new IllegalStateException("Executor " + name + " nicht gefunden", e);
        }
    }
}
