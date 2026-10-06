package de.demo.mes.infra;

/**
 * Liest die Container-Umgebung (docker-compose.yml). Jeder TomEE-Container läuft
 * mit demselben WAR, die Rolle entscheidet nur über Hintergrunddienste.
 */
public final class Umgebung {

    private Umgebung() {
    }

    /** core | fileprocessing | facade | singleton */
    public static String rolle() {
        return text("MES_ROLLE", "core");
    }

    public static String dbUrl() {
        return text("MES_DB_URL", "jdbc:oracle:thin:@//oracle-db:1521/FREEPDB1");
    }

    public static String text(String name, String standard) {
        String wert = System.getenv(name);
        return wert == null || wert.isBlank() ? standard : wert.trim();
    }

    public static int zahl(String name, int standard) {
        try {
            return Integer.parseInt(text(name, String.valueOf(standard)));
        } catch (NumberFormatException e) {
            return standard;
        }
    }

    public static void schlafen(long ms) {
        try {
            Thread.sleep(ms);
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
        }
    }
}
