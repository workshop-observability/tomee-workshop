package de.demo.mes.rest;

import java.util.Map;
import java.util.concurrent.ThreadLocalRandom;

import de.demo.mes.core.BaugruppeService;
import de.demo.mes.core.StammdatenService;
import de.demo.mes.infra.Umgebung;
import de.demo.mes.logging.LogSammler;
import de.demo.mes.monitoring.SzenarioStatus;
import jakarta.ejb.EJB;
import jakarta.ws.rs.Consumes;
import jakarta.ws.rs.DefaultValue;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.MediaType;
import jakarta.ws.rs.core.Response;

/** Die „normalen“ Anwendungsfälle, auf die der Lasttest zielt. */
@Path("")
@Produces(MediaType.APPLICATION_JSON)
public class FachRessource {

    @EJB
    private BaugruppeService baugruppen;

    @EJB
    private StammdatenService stammdaten;

    @EJB
    private LogSammler logSammler;

    /**
     * Health-Check des HAProxy. Im Wartungsmodus (S13) 503 – HAProxy nimmt den Server nach
     * drei Fehlversuchen heraus, laufende Requests laufen zu Ende.
     */
    @GET
    @Path("status")
    public Response status() {
        boolean wartung = SzenarioStatus.INSTANZ.inWartung();
        return Response.status(wartung ? 503 : 200)
                .entity(Map.of("status", wartung ? "wartung" : "ok", "rolle", Umgebung.rolle(),
                        "konfig", Umgebung.text("KONFIG", "?")))
                .build();
    }

    @GET
    @Path("baugruppe/{id}")
    public Map<String, Object> lesen(@PathParam("id") long id) throws Exception {
        return baugruppen.lesen(id);
    }

    @GET
    @Path("baugruppe/zufall")
    public Map<String, Object> zufallLesen() throws Exception {
        return baugruppen.lesen(zufallsId());
    }

    /**
     * @param warten         Sekunden für {@code FOR UPDATE WAIT n}; weglassen = unbegrenzt (wie beim Kunden)
     * @param abfrageTimeout Sekunden für {@code Statement.setQueryTimeout}; weglassen = keiner
     */
    @POST
    @Path("baugruppe/{id}/buchung")
    public Map<String, Object> buchen(@PathParam("id") long id,
                                      @QueryParam("station") @DefaultValue("STATION-1") String station,
                                      @QueryParam("warten") Integer warten,
                                      @QueryParam("abfrageTimeout") Integer abfrageTimeout) throws Exception {
        return baugruppen.buchen(id, station, warten, abfrageTimeout);
    }

    @POST
    @Path("baugruppe/zufall/buchung")
    public Map<String, Object> zufallBuchen(@QueryParam("station") @DefaultValue("STATION-1") String station,
                                            @QueryParam("warten") Integer warten,
                                            @QueryParam("abfrageTimeout") Integer abfrageTimeout) throws Exception {
        return baugruppen.buchen(zufallsId(), station, warten, abfrageTimeout);
    }

    @POST
    @Path("stammdaten/abgleich")
    public Map<String, Object> abgleichen() throws Exception {
        return stammdaten.abgleichen();
    }

    @POST
    @Path("stammdaten/schreiben")
    public Map<String, Object> masterSchreiben() throws Exception {
        return stammdaten.masterSchreiben();
    }

    @GET
    @Path("stammdaten/zufall")
    public Map<String, Object> masterLesen() throws Exception {
        return stammdaten.masterLesen();
    }

    /**
     * Logeintrag des MES-Frameworks (Kunde: „schreibt Logs über die Applikationsserver“,
     * 3 von 7 Mio. Requests am Tag). Landet im {@link LogSammler}, der einmal pro Sekunde schreibt.
     */
    @POST
    @Path("log")
    @Consumes({MediaType.TEXT_PLAIN, MediaType.APPLICATION_JSON, MediaType.WILDCARD})
    public Response log(String text, @QueryParam("station") @DefaultValue("STATION-1") String station) {
        boolean angenommen = logSammler.aufnehmen(station, text);
        return Response.status(angenommen ? 202 : 503)
                .entity(Map.of("angenommen", angenommen))
                .build();
    }

    private static long zufallsId() {
        return ThreadLocalRandom.current().nextLong(1, 10_001);
    }
}
