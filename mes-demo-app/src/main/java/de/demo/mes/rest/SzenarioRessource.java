package de.demo.mes.rest;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import de.demo.mes.core.BaugruppeService;
import de.demo.mes.core.DatenQuellen;
import de.demo.mes.infra.Executoren;
import de.demo.mes.infra.Umgebung;
import de.demo.mes.jms.JmsSzenarien;
import de.demo.mes.logging.LogSammler;
import de.demo.mes.monitoring.ExecutorStatistik;
import de.demo.mes.monitoring.SchedulerJob;
import de.demo.mes.monitoring.SzenarioStatus;
import de.demo.mes.scheduler.EjbZeitplaene;
import de.demo.mes.scheduler.QuartzZeitplaene;
import de.demo.mes.szenario.DbSzenarien;
import de.demo.mes.szenario.JvmSzenarien;
import de.demo.mes.szenario.LangsameBean;
import de.demo.mes.szenario.TransaktionsSzenario;
import jakarta.ejb.EJB;
import jakarta.inject.Inject;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpSession;
import jakarta.ws.rs.DELETE;
import jakarta.ws.rs.DefaultValue;
import jakarta.ws.rs.GET;
import jakarta.ws.rs.POST;
import jakarta.ws.rs.Path;
import jakarta.ws.rs.PathParam;
import jakarta.ws.rs.Produces;
import jakarta.ws.rs.QueryParam;
import jakarta.ws.rs.core.Context;
import jakarta.ws.rs.core.MediaType;

/**
 * Schnittstellen, die gezielt eine Störung erzeugen – für die Szenarien S01–S19 in
 * lasttest/mes_last.py. Jede Schnittstelle erzeugt genau eine Ursache, damit die
 * Wirkung im Dashboard eindeutig zuzuordnen ist.
 */
@Path("szenario")
@Produces(MediaType.APPLICATION_JSON)
public class SzenarioRessource {

    @EJB
    private DbSzenarien db;
    @EJB
    private BaugruppeService baugruppen;
    @EJB
    private TransaktionsSzenario transaktion;
    @EJB
    private LangsameBean langsameBean;
    @EJB
    private EjbZeitplaene ejbZeitplaene;
    @EJB
    private QuartzZeitplaene quartzZeitplaene;
    @EJB
    private JmsSzenarien jms;
    @EJB
    private LogSammler logSammler;
    @Inject
    private JvmSzenarien jvm;

    // ─── S01, S06: Sperre durch die Replikation ────────────────────────────

    @POST
    @Path("db/sperre")
    public Map<String, Object> sperren(@QueryParam("tabelle") @DefaultValue("BAUGRUPPE") String tabelle,
                                       @QueryParam("modus") @DefaultValue("tabelle") String modus,
                                       @QueryParam("von") @DefaultValue("1") long von,
                                       @QueryParam("bis") @DefaultValue("10000") long bis,
                                       @QueryParam("sekunden") @DefaultValue("600") int sekunden) throws Exception {
        return db.sperren(tabelle, modus, von, bis, sekunden);
    }

    @GET
    @Path("db/sperre")
    public List<Map<String, Object>> sperrenAuflisten() {
        return db.sperrenAuflisten();
    }

    @DELETE
    @Path("db/sperre")
    public Map<String, Object> sperrenFreigeben() {
        return Map.of("freigegeben", db.sperrenFreigeben());
    }

    // ─── S02: DB-Verbindungen laufen voll ──────────────────────────────────

    @GET
    @Path("db/langsam")
    public Map<String, Object> langsameAbfrage(@QueryParam("sekunden") @DefaultValue("10") int sekunden,
                                               @QueryParam("datasource") @DefaultValue(DatenQuellen.MES) String ds)
            throws Exception {
        return baugruppen.langsameAbfrage(ds, sekunden);
    }

    // ─── S03: Bean-Pool leer ───────────────────────────────────────────────

    @GET
    @Path("bean/langsam")
    public Map<String, Object> langsameBean(@QueryParam("ms") @DefaultValue("5000") long ms) {
        return mitDauer(() -> langsameBean.arbeiten(ms));
    }

    // ─── S04: HTTP-Threads am Limit ────────────────────────────────────────

    @GET
    @Path("http/langsam")
    public Map<String, Object> langsam(@QueryParam("ms") @DefaultValue("5000") long ms) {
        return mitDauer(() -> {
            Umgebung.schlafen(ms);
            return ms;
        });
    }

    // ─── S05: Executoren aus tomee.xml ─────────────────────────────────────

    @GET
    @Path("executor")
    public List<Map<String, Object>> executoren() {
        List<Map<String, Object>> liste = new ArrayList<>();
        Executoren.NAMEN.forEach(n -> liste.add(ExecutorStatistik.fuer(n).schnappschuss()));
        return liste;
    }

    @POST
    @Path("executor/{name}")
    public Map<String, Object> executorFuellen(@PathParam("name") String name,
                                               @QueryParam("aufgaben") @DefaultValue("100") int aufgaben,
                                               @QueryParam("ms") @DefaultValue("30000") long ms) {
        Executoren.holen(name);
        ExecutorStatistik statistik = ExecutorStatistik.fuer(name);
        int angenommen = 0;
        for (int i = 0; i < aufgaben; i++) {
            if (statistik.einreichen(() -> Umgebung.schlafen(ms))) {
                angenommen++;
            }
        }
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("angenommen", angenommen);
        m.put("abgelehnt", aufgaben - angenommen);
        m.put("zustand", statistik.schnappschuss());
        return m;
    }

    // ─── S06: Timer tickt nicht ────────────────────────────────────────────

    @GET
    @Path("scheduler")
    public Map<String, Object> scheduler() throws Exception {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("timerPoolGroesse (openejb.timer.pool.size)", System.getProperty("openejb.timer.pool.size", "3 (Default)"));
        m.put("quartz", quartzZeitplaene.status());
        m.put("blockierteThreads", SzenarioStatus.INSTANZ.getBlockierteTimerThreads());
        List<Map<String, Object>> jobs = new ArrayList<>();
        SchedulerJob.alle().values().forEach(j -> {
            Map<String, Object> job = new LinkedHashMap<>();
            job.put("scheduler", j.getScheduler());
            job.put("job", j.getJob());
            job.put("sekundenSeitLetztemStart", Math.round(j.getSekundenSeitLetztemStart()));
            job.put("sollIntervall", j.getSollIntervallSekunden());
            job.put("laeufe", j.getLaeufe());
            job.put("laeuftGerade", j.getLaeuftGerade());
            job.put("maxVerspaetungMs", j.getMaxVerspaetungMs());
            job.put("misfires", j.getMisfires());
            job.put("fehler", j.getFehler());
            job.put("uebersprungen", j.getUebersprungen());
            job.put("wartend", j.getWartend());
            jobs.add(job);
        });
        m.put("jobs", jobs);
        return m;
    }

    /** @param art ejb oder quartz */
    @POST
    @Path("scheduler/blockieren")
    public Map<String, Object> schedulerBlockieren(@QueryParam("art") @DefaultValue("ejb") String art,
                                                   @QueryParam("anzahl") @DefaultValue("3") int anzahl,
                                                   @QueryParam("sekunden") @DefaultValue("120") int sekunden)
            throws Exception {
        if ("quartz".equalsIgnoreCase(art)) {
            quartzZeitplaene.blockierenEinplanen(anzahl, sekunden * 1000L);
        } else {
            ejbZeitplaene.blockierenEinplanen(anzahl, sekunden * 1000L);
        }
        return Map.of("art", art, "anzahl", anzahl, "sekunden", sekunden);
    }

    // ─── S11: Job läuft länger als sein Intervall ───────────────────────────

    /** @param schutz ohne | ueberspringen | singleton-lock */
    @POST
    @Path("scheduler/langlaeufer")
    public Map<String, Object> langlaeufer(@QueryParam("intervall") @DefaultValue("10") int intervall,
                                           @QueryParam("laufzeit") @DefaultValue("25") int laufzeit,
                                           @QueryParam("schutz") @DefaultValue("ohne") String schutz) {
        if (intervall < 1 || laufzeit < 1) {
            throw new IllegalArgumentException("intervall und laufzeit müssen mindestens 1 s sein");
        }
        return ejbZeitplaene.langlaeuferStarten(intervall, laufzeit, schutz);
    }

    @DELETE
    @Path("scheduler/langlaeufer")
    public Map<String, Object> langlaeuferStoppen() {
        return Map.of("gestoppt", ejbZeitplaene.langlaeuferStoppen());
    }

    // ─── S07: Transaktion länger als erlaubt ───────────────────────────────

    @GET
    @Path("tx/lang")
    public Map<String, Object> langeTransaktion(@QueryParam("sekunden") @DefaultValue("30") int sekunden,
                                                @QueryParam("timeout") @DefaultValue("0") int timeout,
                                                @QueryParam("sperreId") @DefaultValue("0") long sperreId)
            throws Exception {
        return transaktion.lang(sekunden, timeout, sperreId);
    }

    // ─── S08: HTTP-Sessions ────────────────────────────────────────────────

    /** Legt pro Aufruf eine neue HTTP-Session an (Client ohne Cookie) und hängt Nutzdaten an. */
    @GET
    @Path("session/anlegen")
    public Map<String, Object> session(@Context HttpServletRequest request,
                                       @QueryParam("kb") @DefaultValue("20") int kb) {
        HttpSession session = request.getSession(true);
        session.setAttribute("nutzdaten", new byte[kb * 1024]);
        return Map.of("session", session.getId(), "neu", session.isNew(),
                "timeoutSekunden", session.getMaxInactiveInterval());
    }

    // ─── S09: Heap-Leck (Facade) ───────────────────────────────────────────

    @POST
    @Path("jvm/leck")
    public Map<String, Object> leck(@QueryParam("mb") @DefaultValue("50") int mb) {
        return jvm.leck(mb);
    }

    @DELETE
    @Path("jvm/leck")
    public Map<String, Object> leckFreigeben() {
        return Map.of("freigegebenMb", jvm.leckFreigeben());
    }

    // ─── S10: File Descriptors ─────────────────────────────────────────────

    @POST
    @Path("jvm/dateien")
    public Map<String, Object> dateien(@QueryParam("anzahl") @DefaultValue("500") int anzahl) throws Exception {
        return Map.of("offeneDateien", jvm.dateienOeffnen(anzahl));
    }

    @DELETE
    @Path("jvm/dateien")
    public Map<String, Object> dateienSchliessen() {
        return Map.of("geschlossen", jvm.dateienSchliessen());
    }

    // ─── S12: Nachrichten stauen sich (ActiveMQ / MDB) ──────────────────────

    /** @param art langsam | buchung; gift = Anteil in Prozent, deren Verarbeitung immer scheitert */
    @POST
    @Path("jms/senden")
    public Map<String, Object> jmsSenden(@QueryParam("anzahl") @DefaultValue("10") int anzahl,
                                         @QueryParam("art") @DefaultValue("langsam") String art,
                                         @QueryParam("ms") @DefaultValue("1000") long ms,
                                         @QueryParam("gift") @DefaultValue("0") int gift) {
        return jms.senden(Math.max(0, anzahl), art, Math.max(0, ms), Math.max(0, Math.min(100, gift)));
    }

    @GET
    @Path("jms")
    public Map<String, Object> jmsZustand() {
        return jms.zustand();
    }

    /** Rückstand abbauen: Queue und Dead Letter Queue leerlesen. */
    @DELETE
    @Path("jms")
    public Map<String, Object> jmsLeeren() {
        return jms.leeren();
    }

    // ─── S13: Wartung eines Applikationsservers (N−1) ─────────────────────

    @POST
    @Path("wartung")
    public Map<String, Object> wartungAn() {
        SzenarioStatus.INSTANZ.wartung.set(1);
        return Map.of("wartung", true, "rolle", Umgebung.rolle(),
                "hinweis", "Health-Check /mes/api/status antwortet jetzt 503 – HAProxy nimmt den Server heraus");
    }

    @DELETE
    @Path("wartung")
    public Map<String, Object> wartungAus() {
        SzenarioStatus.INSTANZ.wartung.set(0);
        return Map.of("wartung", false, "rolle", Umgebung.rolle());
    }

    // ─── S14: Speicher außerhalb des Heaps ────────────────────────────────

    @POST
    @Path("jvm/offheap")
    public Map<String, Object> offHeap(@QueryParam("mb") @DefaultValue("50") int mb) {
        return jvm.offHeap(Math.max(0, mb));
    }

    @DELETE
    @Path("jvm/offheap")
    public Map<String, Object> offHeapFreigeben() {
        return Map.of("freigegebenMb", jvm.offHeapFreigeben());
    }

    @POST
    @Path("jvm/threads")
    public Map<String, Object> threads(@QueryParam("anzahl") @DefaultValue("100") int anzahl,
                                       @QueryParam("stackKb") @DefaultValue("256") int stackKb,
                                       @QueryParam("sekunden") @DefaultValue("600") int sekunden) {
        return jvm.threadsStarten(Math.max(0, anzahl), Math.max(1, Math.min(768, stackKb)), Math.max(1, sekunden));
    }

    @DELETE
    @Path("jvm/threads")
    public Map<String, Object> threadsBeenden() {
        return Map.of("beendet", jvm.threadsBeenden());
    }

    // ─── S15: Sitzungsgrenze der Datenbank ────────────────────────────────

    /** @param limit 0 = unbegrenzt */
    @POST
    @Path("db/sitzungslimit")
    public Map<String, Object> sitzungslimit(@QueryParam("benutzer") @DefaultValue("MES_LOCAL") String benutzer,
                                             @QueryParam("limit") @DefaultValue("60") int limit) throws Exception {
        return db.sitzungslimit(benutzer, limit);
    }

    @DELETE
    @Path("db/sitzungslimit")
    public Map<String, Object> sitzungslimitAufheben() {
        return Map.of("sitzungslimit", db.sitzungslimitAufheben());
    }

    // ─── S17: Log-Flut ─────────────────────────────────────────────────────

    /**
     * @param modus        unbegrenzt | verwerfen | blockieren
     * @param schreibLimit Zeilen pro Sekunde, die der Schreiber schafft (0 = ohne Grenze)
     */
    @POST
    @Path("log")
    public Map<String, Object> logKonfigurieren(@QueryParam("modus") @DefaultValue("unbegrenzt") String modus,
                                                @QueryParam("kapazitaet") @DefaultValue("10000") int kapazitaet,
                                                @QueryParam("schreibLimit") @DefaultValue("0") int schreibLimit) {
        return logSammler.konfigurieren(modus, kapazitaet, schreibLimit);
    }

    @GET
    @Path("log")
    public Map<String, Object> logZustand() {
        return logSammler.zustand();
    }

    @DELETE
    @Path("log")
    public Map<String, Object> logZuruecksetzen() {
        return logSammler.zuruecksetzen();
    }

    // ─── S18: Connection-Leck ──────────────────────────────────────────────

    @POST
    @Path("db/leck")
    public Map<String, Object> connectionLeck(@QueryParam("datasource") @DefaultValue(DatenQuellen.MES) String ds,
                                              @QueryParam("anzahl") @DefaultValue("5") int anzahl) throws Exception {
        return db.leck(ds, Math.max(0, anzahl));
    }

    @DELETE
    @Path("db/leck")
    public Map<String, Object> connectionLeckSchliessen() {
        return Map.of("geschlossen", db.leckSchliessen());
    }

    // ─── S19: GC-Spirale ───────────────────────────────────────────────────

    /** Kurzlebiger Müll je Request – zusammen mit dem Heap-Leck (jvm/leck) die GC-Last. */
    @GET
    @Path("jvm/muell")
    public Map<String, Object> muell(@QueryParam("kb") @DefaultValue("512") int kb) {
        return mitDauer(() -> jvm.muell(Math.max(1, Math.min(65536, kb))));
    }

    // ─── Aufräumen ─────────────────────────────────────────────────────────

    @DELETE
    @Path("alle")
    public Map<String, Object> allesZuruecksetzen() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("sperren", db.sperrenFreigeben());
        m.putAll(jvm.zuruecksetzen());
        m.put("geleckteConnections", db.leckSchliessen());
        m.put("sitzungslimit", db.sitzungslimitAufheben());
        m.put("langlaeufer", ejbZeitplaene.langlaeuferStoppen());
        m.put("wartung", SzenarioStatus.INSTANZ.wartung.getAndSet(0) > 0 ? "beendet" : "war aus");
        m.put("logSammler", logSammler.zuruecksetzen().get("verworfenerRueckstand"));
        m.put("jms", jms.leeren());
        m.put("hinweis", "Belegte Timer-, Executor- und Bean-Pools laufen von selbst aus.");
        return m;
    }

    private interface Arbeit {
        Object tun();
    }

    private static Map<String, Object> mitDauer(Arbeit arbeit) {
        long start = System.currentTimeMillis();
        Object ergebnis = arbeit.tun();
        return Map.of("ergebnis", String.valueOf(ergebnis), "dauerMs", System.currentTimeMillis() - start);
    }
}
