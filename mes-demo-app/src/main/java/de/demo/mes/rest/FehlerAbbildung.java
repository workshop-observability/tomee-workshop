package de.demo.mes.rest;

import java.util.LinkedHashMap;
import java.util.Map;

import de.demo.mes.monitoring.Fehlerzaehler;
import de.demo.mes.monitoring.Fehlerzaehler.Art;
import jakarta.ws.rs.WebApplicationException;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;
import jakarta.ws.rs.ext.ExceptionMapper;
import jakarta.ws.rs.ext.Provider;

/**
 * Übersetzt Fehler in HTTP-Status und zählt sie nach Ursache.
 * Ressourcenengpässe werden zu 503 – so sieht sie auch der HAProxy.
 */
@Provider
public class FehlerAbbildung implements ExceptionMapper<Exception> {

    @Override
    public Response toResponse(Exception fehler) {
        if (fehler instanceof WebApplicationException w) {
            return w.getResponse();
        }
        Throwable wurzel = fehler;
        for (Throwable t = fehler; t != null; t = t.getCause()) {
            if (t instanceof IllegalArgumentException) {
                return antwort(400, "EINGABE", t.getMessage());
            }
            wurzel = t;
        }
        Art art = Fehlerzaehler.INSTANZ.zaehlen(fehler);
        int status = switch (art) {
            case SONSTIGE, CLIENT_ABBRUCH -> 500;
            case TRANSAKTION_ABGEBROCHEN -> 409;
            default -> 503;
        };
        return antwort(status, art.name(), wurzel.getClass().getSimpleName() + ": " + wurzel.getMessage());
    }

    private static Response antwort(int status, String art, String meldung) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("fehler", art);
        body.put("meldung", String.valueOf(meldung));
        return Response.status(status).type(MediaType.APPLICATION_JSON).entity(body).build();
    }
}
