#!/usr/bin/env python3
"""
Erzeugt das Grafana-Dashboard der MES-Demo als JSON (grafana/dashboards/mes-jmx.json).

Dashboards als Code: Panels hier ändern, Skript ausführen, Grafana lädt die
Datei innerhalb von 30 s neu (Provisioning).

    python3 grafana/dashboards_erzeugen.py

Aufbau folgt dem JMX Exporter (tomee/jmx-exporter.yaml): eine Zeile je
Metrikgruppe bzw. MBean, Panel-Titel = Metrikname, Beschreibung = MBean und
Attribut. Die Abfragen verwenden nur die Exporter-Metriken selbst, keine
Aufzeichnungsregeln – so lässt sich jedes Panel 1:1 auf die Kundenumgebung
übertragen. Obenauf die sechs Panels in Diagnosereihenfolge (Foliensatz Teil 4).
"""

import json
import sys
from pathlib import Path

ZIEL = Path(__file__).parent / "dashboards"
DS = {"type": "prometheus", "uid": "prometheus"}
INST = 'instance=~"$instanz"'


class Dashboard:
    def __init__(self, uid, titel, beschreibung):
        self.uid, self.titel, self.beschreibung = uid, titel, beschreibung
        self.panels = []
        self.y = 0
        self.x = 0
        self.zeilenhoehe = 0
        self.naechste_id = 1
        self.ziel = self.panels

    def zeile(self, titel, eingeklappt=False):
        self._umbruch()
        if self.ziel is not self.panels:
            self.y = self.panels[-1]["gridPos"]["y"] + 1    # eingeklappte Zeile belegt nur 1 Höhe
        zeile = {"type": "row", "title": titel, "collapsed": eingeklappt, "id": self._id(),
                 "gridPos": {"h": 1, "w": 24, "x": 0, "y": self.y}, "panels": []}
        self.panels.append(zeile)
        self.ziel = zeile["panels"] if eingeklappt else self.panels
        self.y += 1

    def _umbruch(self):
        if self.x:
            self.y += self.zeilenhoehe
            self.x = 0
            self.zeilenhoehe = 0

    def _id(self):
        self.naechste_id += 1
        return self.naechste_id

    def _platz(self, breite, hoehe):
        if self.x + breite > 24:
            self._umbruch()
        pos = {"h": hoehe, "w": breite, "x": self.x, "y": self.y}
        self.x += breite
        self.zeilenhoehe = max(self.zeilenhoehe, hoehe)
        return pos

    def kurve(self, titel, ausdruecke, einheit="short", breite=8, hoehe=8, beschreibung="",
              schwellen=None, max_wert=None, min_wert=None, gestapelt=False, balken=False):
        feld = {"unit": einheit, "custom": {
            "drawStyle": "bars" if balken else "line", "lineWidth": 2, "fillOpacity": 25 if gestapelt else 8,
            "showPoints": "never", "spanNulls": True,
            "stacking": {"mode": "normal" if gestapelt else "none"},
            "thresholdsStyle": {"mode": "line+area" if schwellen else "off"}}}
        if schwellen:
            feld["thresholds"] = _schwellen(schwellen)
        if max_wert is not None:
            feld["max"] = max_wert
        if min_wert is not None:
            feld["min"] = min_wert
        self.ziel.append({
            "type": "timeseries", "title": titel, "description": beschreibung, "id": self._id(),
            "datasource": DS, "gridPos": self._platz(breite, hoehe),
            "fieldConfig": {"defaults": feld, "overrides": []},
            "options": {"legend": {"displayMode": "list", "placement": "bottom"},
                        "tooltip": {"mode": "multi", "sort": "desc"}},
            "targets": _ziele(ausdruecke)})

    def wert(self, titel, ausdruck, einheit="short", breite=4, hoehe=4, beschreibung="",
             schwellen=None, legende=None, farbe_hintergrund=True):
        self.ziel.append({
            "type": "stat", "title": titel, "description": beschreibung, "id": self._id(),
            "datasource": DS, "gridPos": self._platz(breite, hoehe),
            "fieldConfig": {"defaults": {"unit": einheit, "decimals": 1 if einheit == "percentunit" else None,
                                         "thresholds": _schwellen(schwellen or [(None, "green")]),
                                         "color": {"mode": "thresholds"}}, "overrides": []},
            "options": {"colorMode": "background" if farbe_hintergrund else "value", "graphMode": "area",
                        "reduceOptions": {"calcs": ["lastNotNull"], "values": False},
                        "textMode": "value_and_name" if legende else "auto"},
            "targets": _ziele([(ausdruck, legende or "")])})

    def tabelle(self, titel, ausdruck, breite=12, hoehe=8, beschreibung=""):
        self.ziel.append({
            "type": "table", "title": titel, "description": beschreibung, "id": self._id(),
            "datasource": DS, "gridPos": self._platz(breite, hoehe),
            "targets": [{"expr": ausdruck, "format": "table", "instant": True, "refId": "A", "datasource": DS}],
            "transformations": [{"id": "organize", "options": {
                "excludeByName": {"Time": True, "__name__": True, "job": True}}}],
            "fieldConfig": {"defaults": {}, "overrides": []}, "options": {"showHeader": True}})

    def text(self, inhalt, breite=24, hoehe=3):
        self.ziel.append({"type": "text", "title": "", "id": self._id(), "gridPos": self._platz(breite, hoehe),
                            "options": {"mode": "markdown", "content": inhalt}})

    def speichern(self, dateiname, szenario=False):
        """szenario=True: feste Instanzen in den Abfragen, keine Auswahlvariable, 10 min Zeitfenster."""
        self._umbruch()
        instanz_variable = {
            "name": "instanz", "label": "Applikationsserver", "type": "query", "datasource": DS,
            "query": {"query": 'label_values(up{job=~"tomee.*"}, instance)', "refId": "instanz"},
            "definition": 'label_values(up{job=~"tomee.*"}, instance)',
            "multi": True, "includeAll": True, "refresh": 2, "sort": 1,
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]}}
        daten = {
            "uid": self.uid, "title": self.titel, "description": self.beschreibung,
            "tags": ["mes-demo", "szenario"] if szenario else ["mes-demo"],
            "timezone": "browser", "schemaVersion": 39, "version": 1,
            "editable": True, "graphTooltip": 1, "refresh": "5s",
            "time": {"from": "now-10m" if szenario else "now-15m", "to": "now"},
            "timepicker": {"refresh_intervals": ["5s", "10s", "30s", "1m"]},
            "templating": {"list": [] if szenario else [instanz_variable]},
            "annotations": {"list": [
                {"builtIn": 1, "datasource": {"type": "grafana", "uid": "-- Grafana --"}, "enable": True,
                 "hide": True, "iconColor": "rgba(0, 211, 255, 1)", "name": "Annotations & Alerts", "type": "dashboard"},
                {"name": "Absichtliche Störung aktiv", "enable": True, "iconColor": "orange", "datasource": DS,
                 "expr": "sum(mes_szenario_gehaltenesperren + mes_szenario_blockiertetimerthreads"
                         " + mes_szenario_laufendelangetransaktionen) > 0",
                 "step": "10s", "titleFormat": "Szenario aktiv",
                 "textFormat": "Sperre, blockierte Timer oder lange Transaktion"},
                {"name": "Alarme", "enable": True, "iconColor": "red", "datasource": DS,
                 "expr": 'ALERTS{alertstate="firing"}', "step": "15s",
                 "titleFormat": "{{alertname}}", "textFormat": "{{instance}} {{stufe}}"}]},
            "links": [{"type": "dashboards", "tags": ["mes-demo"], "asDropdown": True,
                       "title": "MES-Dashboards", "keepTime": True}],
            "panels": self.panels,
        }
        (ZIEL / dateiname).write_text(json.dumps(daten, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print("geschrieben:", dateiname, len(self.panels), "Panels")


def _schwellen(liste):
    schritte = []
    for wert, farbe in liste:
        schritte.append({"value": wert, "color": farbe})
    if schritte[0]["value"] is not None:
        schritte.insert(0, {"value": None, "color": "green"})
    return {"mode": "absolute", "steps": schritte}


def _ziele(ausdruecke):
    ziele = []
    for i, eintrag in enumerate(ausdruecke):
        expr, legende = eintrag if isinstance(eintrag, tuple) else (eintrag, "")
        ziele.append({"expr": expr, "legendFormat": legende, "refId": chr(65 + i), "datasource": DS})
    return ziele


# Standard-Ampel für Verhältnisse (Startwerte, siehe prometheus/regeln.yml)
AUSLASTUNG = [(None, "green"), (0.8, "orange"), (0.95, "red")]


def jmx_dashboard():
    d = Dashboard("mes-jmx", "MES – JMX Exporter",
                  "Alle Werte, die der JMX Exporter aus TomEE liefert – eine Zeile je MBean-Gruppe.")

    # ─── Überblick: sechs Panels in Diagnosereihenfolge ──────────────────────
    d.zeile("Überblick – 1–2: ob es ein Problem gibt · 3: dass es eng ist · 4–6: warum")
    d.kurve("1 Durchsatz und Fehler",
            [(f"rate(tomcat_requests_total{{{INST}}}[1m])", "{{instance}} Requests"),
             (f"rate(tomcat_errors_total{{{INST}}}[1m])", "{{instance}} Fehler")], "reqps",
            beschreibung="Catalina:type=GlobalRequestProcessor → requestCount, errorCount (Zähler, deshalb rate)")
    d.kurve("2 Mittlere Antwortzeit",
            [(f"rate(tomcat_processing_time_ms_total{{{INST}}}[1m]) / rate(tomcat_requests_total{{{INST}}}[1m])",
              "{{instance}}")], "ms",
            beschreibung="processingTime / requestCount – beides aus Catalina:type=GlobalRequestProcessor")
    d.kurve("3 HTTP-Threads belegt / max",
            [(f"tomcat_threadpool_currentthreadsbusy{{{INST}}} / (tomcat_threadpool_maxthreads{{{INST}}} > 0)", "{{instance}}"),
             (f"tomcat_executor_activecount{{{INST}}} / tomcat_executor_maxthreads{{{INST}}}", "{{instance}} Executor")],
            "percentunit", schwellen=AUSLASTUNG, max_wert=1, min_wert=0,
            beschreibung="Catalina:type=ThreadPool → currentThreadsBusy / maxThreads; "
                         "mit Executor (optimierte Konfig) Catalina:type=Executor → activeCount / maxThreads")
    d.kurve("4 JDBC-Pool aktiv / max",
            [(f"tomee_datasource_active{{{INST}}} / tomee_datasource_maxactive{{{INST}}}", "{{instance}} {{datasource}}")],
            "percentunit", schwellen=AUSLASTUNG, max_wert=1, min_wert=0,
            beschreibung="openejb.management:ObjectType=datasources,DataSource=… → Active / MaxActive")
    d.kurve("5 GC-Zeitanteil und Old Gen",
            [(f"sum by (instance) (rate(jvm_gc_collection_seconds_sum{{{INST}}}[1m]))", "{{instance}} GC-Anteil"),
             (f'jvm_memory_pool_used_bytes{{pool=~"G1 Old Gen|Tenured Gen",{INST}}} / jvm_memory_pool_max_bytes{{pool=~"G1 Old Gen|Tenured Gen",{INST}}}',
              "{{instance}} Old Gen")], "percentunit", schwellen=[(None, "green"), (0.8, "orange"), (0.95, "red")],
            min_wert=0, beschreibung="java.lang:type=GarbageCollector → CollectionTime (rate = Zeitanteil); "
                                     "java.lang:type=MemoryPool,name=G1 Old Gen bzw. Tenured Gen (Serial-GC) → Usage")
    d.kurve("6 Prozess-CPU",
            [(f"jvm_os_process_cpu_load{{{INST}}}", "{{instance}}")], "percentunit", max_wert=1, min_wert=0,
            beschreibung="java.lang:type=OperatingSystem → ProcessCpuLoad (bezogen auf die sichtbaren Kerne). "
                         "CPU-Drosselung durch das Container-Limit sieht die JVM nicht – siehe letzte Zeile")

    # ─── Catalina: HTTP-Connector ────────────────────────────────────────────
    d.zeile("tomcat_threadpool_* · tomcat_executor_* – Catalina:type=ThreadPool / Executor")
    d.kurve("tomcat_threadpool_currentthreadsbusy / currentthreadcount / maxthreads",
            [(f"tomcat_threadpool_currentthreadsbusy{{{INST}}}", "{{instance}} busy"),
             (f"tomcat_threadpool_currentthreadcount{{{INST}}}", "{{instance}} vorhanden"),
             (f"tomcat_threadpool_maxthreads{{{INST}}} > 0", "{{instance}} max")],
            beschreibung="Catalina:type=ThreadPool,name=\"http-nio-8080\". Zollner-Konfig: stiller Default maxThreads 200. "
                         "Mit Executor meldet der Connector maxThreads = -1 – dann gilt tomcat_executor_*")
    d.kurve("tomcat_threadpool_connectioncount / keepalivecount",
            [(f"tomcat_threadpool_connectioncount{{{INST}}}", "{{instance}} offen"),
             (f"tomcat_threadpool_keepalivecount{{{INST}}}", "{{instance}} keep-alive")],
            beschreibung="→ connectionCount (Limit maxConnections, Default 8192), keepAliveCount")
    d.kurve("tomcat_executor_activecount / queuesize / maxthreads",
            [(f"tomcat_executor_activecount{{{INST}}}", "{{instance}} aktiv"),
             (f"tomcat_executor_queuesize{{{INST}}}", "{{instance}} Queue"),
             (f"tomcat_executor_maxthreads{{{INST}}}", "{{instance}} max")],
            beschreibung="Catalina:type=Executor,name=tomcatThreadPool – nur mit Executor in server.xml (optimierte Konfig)")

    d.zeile("tomcat_requests / errors / processing_time · tomcat_sessions_* – Catalina:type=GlobalRequestProcessor / Manager")
    d.kurve("tomcat_requests_total · tomcat_errors_total (rate)",
            [(f"rate(tomcat_requests_total{{{INST}}}[1m])", "{{instance}} Requests"),
             (f"rate(tomcat_errors_total{{{INST}}}[1m])", "{{instance}} Fehler")], "reqps",
            beschreibung="GlobalRequestProcessor → requestCount, errorCount. Zähler seit Start – nie direkt anzeigen")
    d.kurve("tomcat_request_max_time_ms",
            [(f"tomcat_request_max_time_ms{{{INST}}}", "{{instance}}")], "ms",
            beschreibung="→ maxTime: längste Anfrage seit Start (wird nicht zurückgesetzt)")
    d.kurve("tomcat_sessions_activesessions",
            [(f"tomcat_sessions_activesessions{{{INST}}}", "{{instance}} {{context}}")],
            beschreibung="Catalina:type=Manager,context=/mes → activeSessions (Session-Timeout 30 min)")

    # ─── TomEE ───────────────────────────────────────────────────────────────
    d.zeile("tomee_datasource_* – openejb.management:ObjectType=datasources")
    d.kurve("tomee_datasource_active / idle / maxactive",
            [(f"tomee_datasource_active{{{INST}}}", "{{instance}} {{datasource}} active"),
             (f"tomee_datasource_idle{{{INST}}}", "{{instance}} {{datasource}} idle"),
             (f"tomee_datasource_maxactive{{{INST}}}", "{{instance}} {{datasource}} max")],
            beschreibung="→ Active, Idle, MaxActive (Zollner: 50 bzw. 20)")
    d.kurve("tomee_datasource_waitcount",
            [(f"tomee_datasource_waitcount{{{INST}}}", "{{instance}} {{datasource}}")],
            schwellen=[(None, "green"), (1, "orange"), (5, "red")],
            beschreibung="→ WaitCount: Threads, die gerade auf eine Connection warten. "
                         "Sie geben nach MaxWait auf (effektiv 30 s, obwohl tomee.xml maxWaitTime = -1 setzt)")
    d.kurve("tomee_datasource_borrowedcount_total · returnedcount_total (rate)",
            [(f"rate(tomee_datasource_borrowedcount_total{{{INST}}}[1m])", "{{instance}} {{datasource}} geliehen"),
             (f"rate(tomee_datasource_returnedcount_total{{{INST}}}[1m])", "{{instance}} {{datasource}} zurück")], "ops",
            beschreibung="→ BorrowedCount, ReturnedCount. Ausleihen ≈ 0 bei vollem Pool = nichts geht mehr")
    d.kurve("tomee_datasource_removeabandonedcount_total (increase 5m)",
            [(f"increase(tomee_datasource_removeabandonedcount_total{{{INST}}}[5m]) > 0", "{{instance}} {{datasource}}")],
            balken=True, beschreibung="→ RemoveAbandonedCount: vom Pool zwangsweise zurückgeholte Connections")
    d.tabelle("tomee_datasource_maxactive / maxidle / minidle / maxwait / removeabandonedtimeout – so sieht TomEE die Konfiguration",
              f"max by (instance, datasource, __name__) ({{__name__=~\"tomee_datasource_(maxactive|maxidle|minidle|maxwait|removeabandonedtimeout)\",{INST}}})",
              breite=16, beschreibung="MaxWait = 30000 trotz maxWaitTime = -1 in der Zollner-Konfig")

    d.zeile("tomee_beanpool_* · tomee_bean_invocation* – openejb.management:j2eeType=Pool / Invocations")
    d.kurve("tomee_beanpool_instancesactive / maxsize",
            [(f"tomee_beanpool_instancesactive{{{INST}}} / tomee_beanpool_maxsize{{{INST}}} > 0", "{{instance}} {{bean}}")],
            "percentunit", schwellen=AUSLASTUNG, max_wert=1, min_wert=0,
            beschreibung="…,StatelessSessionBean=…,j2eeType=Pool → InstancesActive / MaxSize "
                         "(Zollner: 50, strictPooling). Nur Beans mit aktiven Instanzen")
    d.kurve("tomee_beanpool_availablepermits",
            [(f"tomee_beanpool_availablepermits{{{INST}}} < tomee_beanpool_maxsize{{{INST}}}", "{{instance}} {{bean}}")],
            beschreibung="→ AvailablePermits. 0 = der nächste Aufrufer wartet bis accessTimeout (30 s)")
    d.kurve("tomee_beanpool_accesstimeouts_total (increase 1m)",
            [(f"sum by (instance, bean) (increase(tomee_beanpool_accesstimeouts_total{{{INST}}}[1m])) > 0", "{{instance}} {{bean}}")],
            balken=True, beschreibung="→ AccessTimeouts. Jeder Wert = ein Aufrufer, der 30 s gewartet und dann einen Fehler bekommen hat")
    d.kurve("tomee_bean_invocations_total (rate)",
            [(f"sum by (instance, bean) (rate(tomee_bean_invocations_total{{{INST}}}[1m])) > 0", "{{instance}} {{bean}}")],
            "ops", breite=12, beschreibung="…,j2eeType=Invocations → InvocationCount")
    d.kurve("tomee_bean_invocation_time_ms_total / invocations_total",
            [(f"sum by (instance, bean) (rate(tomee_bean_invocation_time_ms_total{{{INST}}}[1m])) / "
              f"sum by (instance, bean) (rate(tomee_bean_invocations_total{{{INST}}}[1m]))", "{{instance}} {{bean}}")],
            "ms", breite=12, beschreibung="InvocationTime / InvocationCount = mittlere Laufzeit je Aufruf")

    d.zeile("tomee_executor_* – openejb.management:j2eeType=Resource (ManagedExecutorServices aus tomee.xml)")
    d.kurve("tomee_executor_activecount / poolsize",
            [(f"tomee_executor_activecount{{{INST}}} > 0", "{{instance}} {{executor}} aktiv"),
             (f"tomee_executor_poolsize{{{INST}}} > 0", "{{instance}} {{executor}} Threads")],
            beschreibung="→ activeCount, poolSize. Über corePoolSize wächst der Pool erst bei voller Queue")
    d.kurve("tomee_executor_queuesize",
            [(f"tomee_executor_queuesize{{{INST}}} > 0", "{{instance}} {{executor}}")],
            beschreibung="→ queueSize (Zollner: Queue = 1000 bei allen Executoren)")
    d.tabelle("tomee_executor_corepoolsize / maximumpoolsize / largestpoolsize",
              f"max by (instance, executor, __name__) ({{__name__=~\"tomee_executor_(corepoolsize|maximumpoolsize|largestpoolsize)\",{INST}}})",
              breite=8, beschreibung="Konfiguration (Core / Max) und bisher größte Poolgröße")

    d.zeile("tomee_transactions_* · quartz_* – openejb.management:j2eeType=TransactionManager / quartz:type=QuartzScheduler")
    d.kurve("tomee_transactions_active",
            [(f"tomee_transactions_active{{{INST}}}", "{{instance}}")],
            beschreibung="TransactionManager → active. Das Attribut defaultTransactionTimeout zeigt NICHT den gesetzten Wert")
    d.kurve("tomee_transactions_commits_total · rollbacks_total (rate)",
            [(f"rate(tomee_transactions_commits_total{{{INST}}}[1m])", "{{instance}} commits"),
             (f"rate(tomee_transactions_rollbacks_total{{{INST}}}[1m])", "{{instance}} rollbacks")], "ops",
            beschreibung="→ commits, rollbacks")
    d.kurve("quartz_threadpool_size",
            [(f"quartz_threadpool_size{{{INST}}}", "{{instance}} {{scheduler}}")],
            beschreibung="quartz:type=QuartzScheduler → ThreadPoolSize. OpenEJB-TimerService-Scheduler = alle EJB-Timer "
                         "der JVM (openejb.timer.pool.size, Default 3)")

    # ─── JVM (Standardmetriken des Agents + java.lang:type=OperatingSystem) ──
    d.zeile("jvm_memory_* · jvm_gc_* – java.lang:type=Memory / MemoryPool / GarbageCollector")
    d.kurve("jvm_memory_used_bytes / max_bytes {area=heap}",
            [(f'sum by (instance) (jvm_memory_used_bytes{{area="heap",{INST}}})', "{{instance}} belegt"),
             (f'sum by (instance) (jvm_memory_max_bytes{{area="heap",{INST}}})', "{{instance}} max")], "bytes",
            beschreibung="java.lang:type=Memory → HeapMemoryUsage. max = -Xmx")
    d.kurve("jvm_memory_pool_used_bytes {Old Gen, Metaspace}",
            [(f'jvm_memory_pool_used_bytes{{pool=~"G1 Old Gen|Tenured Gen|Metaspace",{INST}}}', "{{instance}} {{pool}}"),
             (f'jvm_buffer_pool_used_bytes{{pool="direct",{INST}}}', "{{instance}} direct buffer")], "bytes",
            beschreibung="java.lang:type=MemoryPool; java.nio:type=BufferPool,name=direct. Old Gen ohne Rückgang = Leck. "
                         "Metaspace und Direct Buffer zählen gegen das Container-Limit, nicht gegen -Xmx")
    d.kurve("jvm_gc_collection_seconds_sum / count",
            [(f"sum by (instance, gc) (rate(jvm_gc_collection_seconds_sum{{{INST}}}[1m])) / "
              f"sum by (instance, gc) (rate(jvm_gc_collection_seconds_count{{{INST}}}[1m]))", "{{instance}} {{gc}}")],
            "s", beschreibung="java.lang:type=GarbageCollector → CollectionTime / CollectionCount = mittlere Pause")

    d.zeile("jvm_threads_* · jvm_os_* · process_* – java.lang:type=Threading / OperatingSystem")
    d.kurve("jvm_threads_state",
            [(f"sum by (instance, state) (jvm_threads_state{{{INST}}}) > 0", "{{instance}} {{state}}")],
            beschreibung="java.lang:type=Threading. Viele BLOCKED = Lock-Konkurrenz, viele WAITING = warten auf Pool/DB. "
                         "jvm_threads_deadlocked > 0 = Deadlock")
    d.kurve("jvm_os_open_file_descriptors / max_file_descriptors",
            [(f"jvm_os_open_file_descriptors{{{INST}}} / jvm_os_max_file_descriptors{{{INST}}}", "{{instance}}")],
            "percentunit", schwellen=[(None, "green"), (0.7, "orange"), (0.85, "red")], min_wert=0,
            beschreibung="OperatingSystem → OpenFileDescriptorCount / MaxFileDescriptorCount – der Absolutwert allein sagt nichts")
    d.kurve("process_start_time_seconds (Neustarts) · up",
            [(f'changes(process_start_time_seconds{{{INST}}}[10m]) > 0', "{{instance}} Neustarts (10 min)"),
             (f'up{{job=~"tomee.*",{INST}}} == 0', "{{instance}} nicht erreichbar")], balken=True,
            beschreibung="Die JVM meldet einen OOM-Kill des Containers nie selbst – sichtbar nur als Neustart oder Lücke")

    # ─── Eigene MBeans der Demo-App ──────────────────────────────────────────
    d.zeile("mes_* – eigene MBeans der Demo-App (mes.demo:*), bei Zollner (noch) nicht vorhanden")
    d.kurve("mes_oracle_blockiertesessions · laengstewartezeitsekunden",
            [("max(mes_oracle_blockiertesessions)", "blockierte Sessions"),
             ("max(mes_oracle_laengstewartezeitsekunden)", "längste Wartezeit (s)")],
            beschreibung="mes.demo:type=OracleSperren (nur Singleton, eigene Verbindung MES_MONITOR)")
    d.kurve("mes_jdbc_aeltesteausleihesekunden",
            [(f"mes_jdbc_aeltesteausleihesekunden{{{INST}}}", "{{instance}} {{datasource}}")], "s",
            schwellen=[(None, "green"), (60, "orange"), (300, "red")],
            beschreibung="mes.demo:type=JdbcZugriff → AeltesteAusleiheSekunden. Eine Sperre zeigt sich als stetig wachsender Wert")
    d.kurve("mes_scheduler_sekundenseitletztemstart",
            [(f'mes_scheduler_sekundenseitletztemstart{{aufgabe!="blockierer",{INST}}}', "{{instance}} {{scheduler}}/{{aufgabe}}")],
            "s", schwellen=[(None, "green"), (120, "orange"), (240, "red")],
            beschreibung="mes.demo:type=SchedulerJob → SekundenSeitLetztemStart. Heartbeat: Sägezahn 0…10 s ist gesund")
    d.kurve("mes_fehler_total (increase 1m)",
            [(f"sum by (art) (increase(mes_fehler_total{{{INST}}}[1m])) > 0", "{{art}}")],
            balken=True, gestapelt=True, breite=12,
            beschreibung="mes.demo:type=Fehler – Fehler nach Ursache")
    d.kurve("mes_socket_offeneverbindungen · wartendeverbindungen",
            [(f"sum by (instance) (mes_socket_offeneverbindungen{{{INST}}})", "{{instance}} offen"),
             (f"sum by (instance) (mes_socket_wartendeverbindungen{{{INST}}})", "{{instance}} warten auf Thread")],
            breite=12, beschreibung="mes.demo:type=SocketServer,port=… (FileProcessing, 50000–50004)")

    # ─── Nicht aus JMX ───────────────────────────────────────────────────────
    d.zeile("Nicht aus JMX: Container (cAdvisor) und HAProxy – was die JVM nicht sehen kann", eingeklappt=True)
    d.kurve("container_memory_working_set_bytes / spec_memory_limit_bytes",
            [('max by (rolle) (container_memory_working_set_bytes{rolle=~"core|fileprocessing|singleton|facade"})', "{{rolle}} belegt"),
             ('max by (rolle) (container_spec_memory_limit_bytes{rolle=~"core|fileprocessing|singleton|facade"} > 0)', "{{rolle}} Limit")],
            "bytes", beschreibung="cAdvisor. Zollner Facade: -Xmx 7168M bei Limit 2000M")
    d.kurve("container_cpu_cfs_throttled_seconds_total (rate)",
            [('sum by (rolle) (rate(container_cpu_cfs_throttled_seconds_total{rolle!=""}[1m])) > 0', "{{rolle}}")], "s",
            beschreibung="cAdvisor: Zeit, in der der Container sein CPU-Kontingent aufgebraucht hatte")
    d.kurve("haproxy_backend_current_queue · http_responses_total{5xx}",
            [('haproxy_backend_current_queue{proxy=~"core|fileprocessing|singleton"}', "Queue {{proxy}}"),
             ('sum by (proxy) (rate(haproxy_backend_http_responses_total{code="5xx"}[1m]))', "5xx/s {{proxy}}")],
            beschreibung="HAProxy-Prometheus-Endpunkt :8989/metrics")
    d.speichern("mes-jmx.json")


# ─── Ein Dashboard je Lastszenario ──────────────────────────────────────────
# Titel und „Worauf es ankommt“ kommen aus SZENARIEN in lasttest/mes_last.py
# (dieselbe Quelle wie Laststeuerung und CLI). Oben die Kacheln mit den Werten,
# die das Szenario entscheiden, darunter die Verläufe in Ursachenreihenfolge.
# Die Instanzen sind fest, weil jedes Szenario einen bestimmten Server belastet.

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lasttest"))
from mes_last import SZENARIEN  # noqa: E402

CORE, SINGLETON, FP, FACADE = 'instance="core"', 'instance="singleton"', 'instance="fileprocessing"', 'instance="facade"'
FEHLER_JE_MIN = [(None, "green"), (1, "red")]


def szenario(nr, server):
    sz = SZENARIEN[nr]
    d = Dashboard(f"mes-{nr.lower()}", f"MES – {nr} {sz.titel}", sz.beobachten)
    zeilen = [f"**{sz.modul}** · belastet: **{server}** · starten: Laststeuerung `:8070` oder "
              f"`python3 lasttest/mes_last.py --host <vm> szenario {nr}`",
              f"**Worauf es ankommt:** {sz.beobachten}"]
    if sz.voraussetzung:
        zeilen.append(f"**Voraussetzung:** {sz.voraussetzung}")
    d.text("\n\n".join(zeilen), hoehe=3 + bool(sz.voraussetzung))
    return d


def fehler_je_minute(art, inst):
    return f'sum(increase(mes_fehler_total{{art=~"{art}",{inst}}}[1m])) or vector(0)'


def s01():
    d = szenario("S01", "core (über HAProxy), Sperre in Oracle")
    d.wert("Oracle: blockierte Sessions", "max(mes_oracle_blockiertesessions)", schwellen=FEHLER_JE_MIN,
           beschreibung="mes.demo:type=OracleSperren → BlockierteSessions")
    d.wert("JDBC-Pool active/max", f"max(tomee_datasource_active{{{CORE}}} / tomee_datasource_maxactive{{{CORE}}})",
           "percentunit", schwellen=AUSLASTUNG, beschreibung="openejb.management:ObjectType=datasources → Active / MaxActive")
    d.wert("BaugruppeService active/max",
           f'tomee_beanpool_instancesactive{{bean="BaugruppeService",{CORE}}} / tomee_beanpool_maxsize{{bean="BaugruppeService",{CORE}}}',
           "percentunit", schwellen=AUSLASTUNG, beschreibung="j2eeType=Pool → InstancesActive / MaxSize")
    d.wert("HTTP-Threads busy/max", f"tomcat_threadpool_currentthreadsbusy{{{CORE}}} / tomcat_threadpool_maxthreads{{{CORE}}}",
           "percentunit", schwellen=AUSLASTUNG, beschreibung="Catalina:type=ThreadPool → currentThreadsBusy / maxThreads")
    d.wert("Älteste Connection", f"max(mes_jdbc_aeltesteausleihesekunden{{{CORE}}})", "s",
           schwellen=[(None, "green"), (60, "orange"), (300, "red")], beschreibung="mes.demo:type=JdbcZugriff")
    d.wert("BEAN_POOL_TIMEOUT / min", fehler_je_minute("BeanPoolTimeout", CORE), schwellen=FEHLER_JE_MIN,
           beschreibung="mes.demo:type=Fehler → BeanPoolTimeout. Kommt nach 30 s (accessTimeout) – auch für Leser")

    d.zeile("Die Kette von der Ursache zum Symptom")
    d.kurve("① Oracle: blockierte Sessions und längste Wartezeit",
            [("max(mes_oracle_blockiertesessions)", "blockierte Sessions"),
             ("max(mes_oracle_laengstewartezeitsekunden)", "längste Wartezeit (s)")],
            beschreibung="mes_oracle_* – eigene Verbindung MES_MONITOR, sieht die Sperre, auch wenn der Pool voll ist")
    d.kurve("② JDBC-Pool: active / max / wartend",
            [(f"tomee_datasource_active{{{CORE}}}", "{{datasource}} active"),
             (f"tomee_datasource_maxactive{{{CORE}}}", "{{datasource}} max"),
             (f"tomee_datasource_waitcount{{{CORE}}}", "{{datasource}} wartend")],
            beschreibung="tomee_datasource_active, maxactive, waitcount. Jede Connection hängt in Oracle an der Sperre")
    d.kurve("② Älteste ausgeliehene Connection", [(f"mes_jdbc_aeltesteausleihesekunden{{{CORE}}}", "{{datasource}}")], "s",
            schwellen=[(None, "green"), (60, "orange"), (300, "red")],
            beschreibung="mes_jdbc_aeltesteausleihesekunden – wächst sekündlich, solange die Sperre hält")
    d.kurve("③ Bean-Pool BaugruppeService",
            [(f'tomee_beanpool_instancesactive{{bean="BaugruppeService",{CORE}}}', "aktiv"),
             (f'tomee_beanpool_maxsize{{bean="BaugruppeService",{CORE}}}', "max"),
             (f'increase(tomee_beanpool_accesstimeouts_total{{bean="BaugruppeService",{CORE}}}[1m])', "accessTimeouts / min")],
            beschreibung="tomee_beanpool_* – 50/50, danach warten weitere Aufrufer 30 s und scheitern")
    d.kurve("④ HTTP-Threads und HAProxy-Queue",
            [(f"tomcat_threadpool_currentthreadsbusy{{{CORE}}}", "HTTP busy"),
             (f"tomcat_threadpool_maxthreads{{{CORE}}}", "HTTP max"),
             ('haproxy_backend_current_queue{proxy="core"}', "HAProxy-Queue core")],
            beschreibung="Viele Threads belegt, CPU trotzdem niedrig: sie warten, sie rechnen nicht")
    d.kurve("⑤ Fehler nach Ursache (pro Minute)",
            [(f"sum by (art) (increase(mes_fehler_total{{{CORE}}}[1m])) > 0", "{{art}}"),
             ('sum(rate(haproxy_backend_http_responses_total{proxy="core",code="5xx"}[1m])) * 60 > 0', "HAProxy 5xx")],
            balken=True, beschreibung="mes_fehler_total; haproxy_backend_http_responses_total{code=5xx}")
    d.speichern("s01-tabellensperre.json", szenario=True)


def s02():
    d = szenario("S02", "core")
    d.wert("Pool active/max", f"tomee_datasource_active{{{CORE}}} / tomee_datasource_maxactive{{{CORE}}}", "percentunit",
           breite=6, schwellen=AUSLASTUNG, legende="{{datasource}}",
           beschreibung="tomee_datasource_active / maxactive (Master_MES_Connection: 20, MES_Connection: 50)")
    d.wert("Wartende Threads", f"sum(tomee_datasource_waitcount{{{CORE}}})", schwellen=[(None, "green"), (1, "orange"), (5, "red")],
           beschreibung="tomee_datasource_waitcount")
    d.wert("Längste aktuelle Wartezeit", f"max(mes_jdbc_laengsteaktuellewartezeitsekunden{{{CORE}}})", "s",
           schwellen=[(None, "green"), (5, "orange"), (25, "red")],
           beschreibung="mes_jdbc_laengsteaktuellewartezeitsekunden – bricht bei 30 s ab (MaxWait, nicht -1)")
    d.wert("MaxWait laut TomEE", f'max(tomee_datasource_maxwait{{{CORE}}})', "ms",
           beschreibung="tomee_datasource_maxwait – 30000 trotz maxWaitTime = -1 in tomee.xml")
    d.wert("PoolExhausted / min", fehler_je_minute("PoolErschoepft", CORE), breite=6, schwellen=FEHLER_JE_MIN,
           beschreibung="mes.demo:type=Fehler → PoolErschoepft")

    d.zeile("Verlauf")
    d.kurve("Pool: active / idle / max",
            [(f"tomee_datasource_active{{{CORE}}}", "{{datasource}} active"),
             (f"tomee_datasource_idle{{{CORE}}}", "{{datasource}} idle"),
             (f"tomee_datasource_maxactive{{{CORE}}}", "{{datasource}} max")],
            beschreibung="tomee_datasource_active / idle / maxactive")
    d.kurve("Wartende Threads (Pool- und Anwendungssicht)",
            [(f"tomee_datasource_waitcount{{{CORE}}}", "{{datasource}} Pool"),
             (f"mes_jdbc_wartendethreads{{{CORE}}}", "{{datasource}} App")],
            beschreibung="tomee_datasource_waitcount; mes_jdbc_wartendethreads")
    d.kurve("Längste aktuelle Wartezeit auf eine Connection",
            [(f"mes_jdbc_laengsteaktuellewartezeitsekunden{{{CORE}}}", "{{datasource}}")], "s",
            schwellen=[(None, "green"), (5, "orange"), (25, "red")],
            beschreibung="Sägezahn bis 30 s: Die Threads geben nach MaxWait auf")
    d.kurve("Ausleihen pro Sekunde", [(f"rate(tomee_datasource_borrowedcount_total{{{CORE}}}[1m])", "{{datasource}}")], "ops",
            breite=8, beschreibung="tomee_datasource_borrowedcount_total – fällt auf ≈ 0, wenn alles belegt ist")
    d.kurve("Fehler pro Minute", [(f"sum by (art) (increase(mes_fehler_total{{{CORE}}}[1m])) > 0", "{{art}}")],
            breite=8, balken=True, beschreibung="mes_fehler_total – PoolErschoepft = PoolExhaustedException nach MaxWait")
    d.kurve("Oracle: aktive Sessions je DB-User", [("max by (benutzer) (mes_oracle_sitzungen_aktiv)", "{{benutzer}}")],
            breite=8, beschreibung="mes_oracle_sitzungen_aktiv – Gegenprobe aus Oracle-Sicht: keine Sperre, nur Laufzeit")
    d.speichern("s02-db-verbindungen.json", szenario=True)


def s03():
    d = szenario("S03", "core (LangsameBean, ohne Datenbank)")
    bean = f'bean="LangsameBean",{CORE}'
    d.wert("LangsameBean active/max", f"tomee_beanpool_instancesactive{{{bean}}} / tomee_beanpool_maxsize{{{bean}}}",
           "percentunit", breite=5, schwellen=AUSLASTUNG, beschreibung="tomee_beanpool_instancesactive / maxsize")
    d.wert("Freie Beans", f"tomee_beanpool_availablepermits{{{bean}}}", breite=5,
           schwellen=[(None, "red"), (1, "orange"), (10, "green")], beschreibung="tomee_beanpool_availablepermits – 0 = nächster Aufrufer wartet")
    d.wert("AccessTimeouts / min", f"increase(tomee_beanpool_accesstimeouts_total{{{bean}}}[1m])", breite=5,
           schwellen=FEHLER_JE_MIN, beschreibung="tomee_beanpool_accesstimeouts_total")
    d.wert("HTTP-Threads busy", f"tomcat_threadpool_currentthreadsbusy{{{CORE}}}", breite=5,
           schwellen=[(None, "green"), (160, "orange"), (190, "red")], beschreibung="tomcat_threadpool_currentthreadsbusy – Wartende belegen HTTP-Threads")
    d.wert("CPU", f"jvm_os_process_cpu_load{{{CORE}}}", "percentunit", breite=4, beschreibung="jvm_os_process_cpu_load – bleibt niedrig")

    d.zeile("Verlauf")
    d.kurve("Bean-Pool: aktiv / max / frei",
            [(f"tomee_beanpool_instancesactive{{{bean}}}", "aktiv"), (f"tomee_beanpool_maxsize{{{bean}}}", "max"),
             (f"tomee_beanpool_availablepermits{{{bean}}}", "frei")], breite=12,
            beschreibung="openejb.management:…,StatelessSessionBean=LangsameBean,j2eeType=Pool")
    d.kurve("Abgewiesene Aufrufer pro Minute",
            [(f"increase(tomee_beanpool_accesstimeouts_total{{{bean}}}[1m])", "AccessTimeouts (TomEE)"),
             (f'increase(mes_fehler_total{{art="BeanPoolTimeout",{CORE}}}[1m])', "BEAN_POOL_TIMEOUT (App)")],
            breite=12, balken=True, beschreibung="Jeder Wert = ein Aufrufer, der accessTimeout (30 s) gewartet hat")
    d.kurve("HTTP-Threads", [(f"tomcat_threadpool_currentthreadsbusy{{{CORE}}}", "busy"),
                             (f"tomcat_threadpool_maxthreads{{{CORE}}}", "max")], breite=12,
            beschreibung="tomcat_threadpool_currentthreadsbusy – Aufrufer mit und ohne Bean halten je einen Thread")
    d.kurve("Mittlere Laufzeit je Aufruf",
            [(f"rate(tomee_bean_invocation_time_ms_total{{{bean}}}[1m]) / rate(tomee_bean_invocations_total{{{bean}}}[1m])", "LangsameBean"),
             (f"rate(tomcat_processing_time_ms_total{{{CORE}}}[1m]) / rate(tomcat_requests_total{{{CORE}}}[1m])", "HTTP gesamt")],
            "ms", breite=12, beschreibung="tomee_bean_invocation_time_ms_total / invocations_total; tomcat_processing_time_ms_total / requests_total")
    d.speichern("s03-bean-pool.json", szenario=True)


def s04():
    d = szenario("S04", "core (über HAProxy)")
    d.wert("HTTP-Threads busy/max", f"tomcat_threadpool_currentthreadsbusy{{{CORE}}} / tomcat_threadpool_maxthreads{{{CORE}}}",
           "percentunit", breite=5, schwellen=AUSLASTUNG, beschreibung="tomcat_threadpool_currentthreadsbusy / maxthreads")
    d.wert("TCP-Verbindungen", f"tomcat_threadpool_connectioncount{{{CORE}}}", breite=5,
           beschreibung="tomcat_threadpool_connectioncount (Limit maxConnections 8192)")
    d.wert("HAProxy-Queue core", 'haproxy_backend_current_queue{proxy="core"}', breite=5,
           schwellen=[(None, "green"), (1, "orange"), (50, "red")], beschreibung="HAProxy hält Anfragen über maxconn 200 zurück")
    d.wert("HAProxy 5xx / min", 'sum(increase(haproxy_backend_http_responses_total{proxy="core",code="5xx"}[1m])) or vector(0)',
           breite=5, schwellen=FEHLER_JE_MIN, beschreibung="503 nach timeout queue (30 s)")
    d.wert("CPU", f"jvm_os_process_cpu_load{{{CORE}}}", "percentunit", breite=4, beschreibung="jvm_os_process_cpu_load – niedrig trotz Vollauslastung")

    d.zeile("Verlauf")
    d.kurve("HTTP-Threads: busy / vorhanden / max",
            [(f"tomcat_threadpool_currentthreadsbusy{{{CORE}}}", "busy"),
             (f"tomcat_threadpool_currentthreadcount{{{CORE}}}", "vorhanden"),
             (f"tomcat_threadpool_maxthreads{{{CORE}}}", "max")],
            beschreibung="Catalina:type=ThreadPool – Zollner-Konfig: stiller Default 200")
    d.kurve("HAProxy: Sessions und Queue (core)",
            [('haproxy_backend_current_sessions{proxy="core"}', "Sessions"),
             ('haproxy_backend_current_queue{proxy="core"}', "Queue")],
            beschreibung="haproxy_backend_current_sessions / current_queue – die Warteschlange steht vor Tomcat")
    d.kurve("HAProxy: Antworten je Statusklasse",
            [('sum by (code) (rate(haproxy_backend_http_responses_total{proxy="core"}[1m])) > 0', "{{code}}")], "reqps",
            gestapelt=True, beschreibung="haproxy_backend_http_responses_total")
    d.kurve("Durchsatz und mittlere Antwortzeit",
            [(f"rate(tomcat_requests_total{{{CORE}}}[1m])", "Requests/s"),
             (f"rate(tomcat_processing_time_ms_total{{{CORE}}}[1m]) / rate(tomcat_requests_total{{{CORE}}}[1m]) / 1000", "Antwortzeit (s)")],
            breite=12, beschreibung="tomcat_requests_total, tomcat_processing_time_ms_total")
    d.kurve("Prozess-CPU", [(f"jvm_os_process_cpu_load{{{CORE}}}", "core")], "percentunit", breite=12, max_wert=1, min_wert=0,
            beschreibung="jvm_os_process_cpu_load – volle Threads bei niedriger CPU = warten, nicht rechnen")
    d.speichern("s04-http-threads.json", szenario=True)


def s05():
    d = szenario("S05", "singleton (ManagedExecutorServices aus tomee.xml)")
    ex = SINGLETON
    d.wert("Aktive Aufgaben", f"sum(tomee_executor_activecount{{{ex}}})", breite=5, beschreibung="tomee_executor_activecount")
    d.wert("Aufgaben in Queues", f"sum(tomee_executor_queuesize{{{ex}}})", breite=5,
           schwellen=[(None, "green"), (500, "orange"), (900, "red")], beschreibung="tomee_executor_queuesize (Zollner: Queue 1000)")
    d.wert("Threads über Core", f"sum(clamp_min(tomee_executor_poolsize{{{ex}}} - tomee_executor_corepoolsize{{{ex}}}, 0))", breite=5,
           schwellen=[(None, "green"), (1, "orange")],
           beschreibung="poolSize − corePoolSize. Wird erst > 0, wenn die Queue voll ist")
    d.wert("Abgelehnt (5 min)", f"sum(increase(mes_executor_abgelehnt_total{{{ex}}}[5m])) or vector(0)", breite=5,
           schwellen=FEHLER_JE_MIN, beschreibung="mes.demo:type=Executor → Abgelehnt (RejectedExecutionException)")
    d.wert("JVM-Threads", f"jvm_threads_current{{{ex}}}", breite=4, beschreibung="jvm_threads_current")

    d.zeile("Verlauf je Executor")
    d.kurve("Threads im Pool (poolSize) und Core",
            [(f"tomee_executor_poolsize{{{ex}}} > 0", "{{executor}} Threads"),
             (f"tomee_executor_corepoolsize{{{ex}}} and tomee_executor_activecount{{{ex}}} > 0", "{{executor}} Core")],
            beschreibung="tomee_executor_poolsize / corepoolsize – bleibt bei Core, bis die Queue voll ist, dann springt sie")
    d.kurve("Queue", [(f"tomee_executor_queuesize{{{ex}}} > 0", "{{executor}}")],
            beschreibung="tomee_executor_queuesize")
    d.kurve("Freie Queue-Plätze", [(f"mes_executor_queue_frei{{{ex}}} and tomee_executor_activecount{{{ex}}} > 0", "{{executor}}")],
            beschreibung="mes_executor_queue_frei – bei 0 wächst der Pool Richtung maximumPoolSize, bei Max: Ablehnung")
    d.kurve("Aktive Aufgaben", [(f"tomee_executor_activecount{{{ex}}} > 0", "{{executor}}")], breite=8,
            beschreibung="tomee_executor_activecount")
    d.kurve("Abgelehnte Aufgaben pro Minute", [(f"increase(mes_executor_abgelehnt_total{{{ex}}}[1m]) > 0", "{{executor}}")],
            breite=8, balken=True, beschreibung="mes_executor_abgelehnt_total – z. B. MslHandling mit 1050 Aufgaben")
    d.kurve("JVM-Threads", [(f"jvm_threads_current{{{ex}}}", "gesamt")], breite=8,
            beschreibung="jvm_threads_current – jeder Thread über Core kostet Stack-Speicher außerhalb des Heaps")
    d.tabelle("Konfiguration je Executor (so sieht TomEE sie)",
              f"max by (executor, __name__) ({{__name__=~\"tomee_executor_(corepoolsize|maximumpoolsize|largestpoolsize)\",{ex}}})",
              breite=24, hoehe=7, beschreibung="corePoolSize / maximumPoolSize / largestPoolSize")
    d.speichern("s05-executor.json", szenario=True)


def s06():
    d = szenario("S06", "singleton (Timer), Sperre über core")
    hb = f'aufgabe="heartbeat",{SINGLETON}'
    d.wert("Heartbeat EJB-Timer", f'mes_scheduler_sekundenseitletztemstart{{scheduler="ejb",{hb}}}', "s",
           schwellen=[(None, "green"), (20, "orange"), (40, "red")], beschreibung="Soll 10 s. Steigt linear, wenn der Timer nicht mehr tickt")
    d.wert("Heartbeat Quartz", f'mes_scheduler_sekundenseitletztemstart{{scheduler="quartz",{hb}}}', "s",
           schwellen=[(None, "green"), (20, "orange"), (40, "red")], beschreibung="eigener Quartz-Scheduler (5 Threads)")
    d.wert("Laufende EJB-Timer-Jobs", f'sum(mes_scheduler_laeuftgerade{{scheduler="ejb",{SINGLETON}}}) + '
                                      f'max(mes_szenario_blockiertetimerthreads{{{SINGLETON}}})',
           schwellen=[(None, "green"), (2, "orange"), (3, "red")],
           beschreibung="belegte Timer-Threads (Jobs + Blockierer). 3 = openejb.timer.pool.size erreicht")
    d.wert("Oracle: blockierte Sessions", "max(mes_oracle_blockiertesessions)", schwellen=FEHLER_JE_MIN,
           beschreibung="Ursache sperre: der Stammdatenabgleich hängt an BAUGRUPPE")
    d.wert("Misfires (10 min)", f"sum(increase(mes_scheduler_misfires_total{{{SINGLETON}}}[10m])) or vector(0)",
           schwellen=FEHLER_JE_MIN, beschreibung="Erst nachträglich sichtbar, wenn wieder ein Thread frei ist")
    d.wert("Fehler (10 min)", f"sum(increase(mes_scheduler_fehler_total{{{SINGLETON}}}[10m])) or vector(0)",
           beschreibung="bleibt 0 – der Timer schweigt, er scheitert nicht")

    d.zeile("Verlauf")
    d.kurve("Sekunden seit letztem Lauf",
            [(f'mes_scheduler_sekundenseitletztemstart{{aufgabe!="blockierer",{SINGLETON}}}', "{{scheduler}}/{{aufgabe}}")], "s",
            breite=12, schwellen=[(None, "green"), (120, "orange"), (240, "red")],
            beschreibung="mes_scheduler_sekundenseitletztemstart – Sägezahn = gesund, Rampe = tickt nicht")
    d.kurve("Belegte Threads je Scheduler",
            [(f"sum by (scheduler) (mes_scheduler_laeuftgerade{{{SINGLETON}}})", "{{scheduler}} laufend"),
             (f"mes_szenario_blockiertetimerthreads{{{SINGLETON}}}", "Blockierer"),
             (f"quartz_threadpool_size{{{SINGLETON}}}", "Pool {{scheduler}}")], breite=12,
            beschreibung="mes_scheduler_laeuftgerade; quartz_threadpool_size (OpenEJB-TimerService-Scheduler = EJB-Timer, 3)")
    d.kurve("Oracle-Sperre", [("max(mes_oracle_blockiertesessions)", "blockierte Sessions"),
                              ("max(mes_oracle_laengstewartezeitsekunden)", "längste Wartezeit (s)")],
            beschreibung="mes_oracle_* – nur bei Ursache sperre")
    d.kurve("Laufzeit des letzten Laufs",
            [(f'mes_scheduler_letztelaufzeitms{{aufgabe="stammdatenabgleich",{SINGLETON}}}', "{{scheduler}}")], "ms",
            beschreibung="mes_scheduler_letztelaufzeitms – ein Lauf länger als sein Intervall frisst den nächsten")
    d.kurve("Misfires und Verspätung",
            [(f"increase(mes_scheduler_misfires_total{{{SINGLETON}}}[1m]) > 0", "{{scheduler}}/{{aufgabe}} Misfires"),
             (f'mes_scheduler_letzteverspaetungms{{aufgabe!="blockierer",{SINGLETON}}} / 1000 > 1', "{{scheduler}}/{{aufgabe}} Verspätung (s)")],
            beschreibung="mes_scheduler_misfires_total, letzteverspaetungms")
    d.speichern("s06-timer.json", szenario=True)


def s07():
    d = szenario("S07", "core (TransaktionsSzenario)")
    d.wert("Älteste Transaktion", f"mes_transaktionen_aeltestesekunden{{{CORE}}}", "s", breite=5,
           schwellen=[(None, "green"), (60, "orange"), (3600, "red")], beschreibung="mes.demo:type=Transaktionen → AeltesteSekunden")
    d.wert("Über Warnschwelle", f"mes_transaktionen_ueberschwelle{{{CORE}}}", breite=5, schwellen=FEHLER_JE_MIN,
           beschreibung="mes_transaktionen_ueberschwelle (TX_WARN_SEKUNDEN, Demo 60 s)")
    d.wert("Oracle: blockierte Sessions", "max(mes_oracle_blockiertesessions)", breite=5, schwellen=FEHLER_JE_MIN,
           beschreibung="Buchungen auf dieselbe Baugruppe warten auf die Zeilensperre")
    d.wert("Rollbacks (5 min)", f"increase(tomee_transactions_rollbacks_total{{{CORE}}}[5m])", breite=5,
           beschreibung="tomee_transactions_rollbacks_total – der Timeout führt erst am Methodenende zum Rollback")
    d.wert("Aktive Transaktionen", f"tomee_transactions_active{{{CORE}}}", breite=4, beschreibung="tomee_transactions_active")

    d.zeile("Verlauf")
    d.kurve("Älteste laufende Transaktion und Warnschwelle",
            [(f"mes_transaktionen_aeltestesekunden{{{CORE}}}", "älteste (App)"),
             (f"mes_transaktionen_warnschwellesekunden{{{CORE}}}", "Warnschwelle"),
             ("max(mes_oracle_aeltestetransaktionsekunden)", "älteste (Oracle)")], "s", breite=12,
            beschreibung="Läuft über den Timeout hinaus – der Timeout bricht die Arbeit nicht ab")
    d.kurve("Sperre in Oracle", [("max(mes_oracle_blockiertesessions)", "blockierte Sessions"),
                                 ("max(mes_oracle_laengstewartezeitsekunden)", "längste Wartezeit (s)")], breite=12,
            beschreibung="mes_oracle_* – die Sperre hält bis Methodenende")
    d.kurve("Aktive Transaktionen", [(f"tomee_transactions_active{{{CORE}}}", "TomEE"), (f"mes_transaktionen_aktive{{{CORE}}}", "App")],
            beschreibung="tomee_transactions_active; mes_transaktionen_aktive")
    d.kurve("Commits und Rollbacks pro Minute",
            [(f"increase(tomee_transactions_commits_total{{{CORE}}}[1m])", "Commits"),
             (f"increase(tomee_transactions_rollbacks_total{{{CORE}}}[1m])", "Rollbacks")], balken=True,
            beschreibung="tomee_transactions_commits_total / rollbacks_total")
    d.kurve("Fehler pro Minute", [(f"sum by (art) (increase(mes_fehler_total{{{CORE}}}[1m])) > 0", "{{art}}")], balken=True,
            beschreibung="mes_fehler_total – TransaktionAbgebrochen, SperrTimeout")
    d.speichern("s07-transaktion.json", szenario=True)


def s08():
    d = szenario("S08", "core")
    d.wert("Aktive Sessions", f"sum(tomcat_sessions_activesessions{{{CORE}}})", breite=6,
           beschreibung="Catalina:type=Manager → activeSessions")
    d.wert("Neue Sessions / s", f"sum(rate(tomcat_sessions_sessioncounter_total{{{CORE}}}[1m]))", "ops", breite=6,
           beschreibung="tomcat_sessions_sessioncounter_total")
    d.wert("Heap belegt/max", f'sum(jvm_memory_used_bytes{{area="heap",{CORE}}}) / sum(jvm_memory_max_bytes{{area="heap",{CORE}}})',
           "percentunit", breite=6, schwellen=[(None, "green"), (0.8, "orange"), (0.9, "red")], beschreibung="jvm_memory_used_bytes / max_bytes")
    d.wert("Old Gen", f'jvm_memory_pool_used_bytes{{pool=~"G1 Old Gen|Tenured Gen",{CORE}}}', "bytes", breite=6,
           beschreibung="jvm_memory_pool_used_bytes{pool=~\"G1 Old Gen|Tenured Gen\"} – Sessions überleben GC")

    d.zeile("Verlauf")
    d.kurve("Aktive Sessions", [(f"tomcat_sessions_activesessions{{{CORE}}}", "{{context}}")], breite=12,
            beschreibung="Steigt und bleibt 30 min (Session-Timeout)")
    d.kurve("Sessions angelegt / abgelaufen pro Sekunde",
            [(f"rate(tomcat_sessions_sessioncounter_total{{{CORE}}}[1m])", "angelegt"),
             (f"rate(tomcat_sessions_expiredsessions_total{{{CORE}}}[1m])", "abgelaufen")], "ops", breite=12,
            beschreibung="tomcat_sessions_sessioncounter_total / expiredsessions_total")
    d.kurve("Heap belegt / max",
            [(f'sum(jvm_memory_used_bytes{{area="heap",{CORE}}})', "belegt"),
             (f'sum(jvm_memory_max_bytes{{area="heap",{CORE}}})', "max"),
             (f'jvm_memory_pool_used_bytes{{pool=~"G1 Old Gen|Tenured Gen",{CORE}}}', "Old Gen")], "bytes",
            beschreibung="Die Untergrenze nach jedem GC steigt – das ist der gehaltene Session-Speicher")
    d.kurve("GC-Zeitanteil", [(f"sum(rate(jvm_gc_collection_seconds_sum{{{CORE}}}[1m]))", "core")], "percentunit",
            schwellen=[(None, "green"), (0.05, "orange"), (0.1, "red")], beschreibung="jvm_gc_collection_seconds_sum (rate)")
    d.kurve("Heap pro Session",
            [(f'sum(jvm_memory_used_bytes{{area="heap",{CORE}}}) / sum(tomcat_sessions_activesessions{{{CORE}}} > 0)', "Heap / Session")],
            "bytes", beschreibung="grobe Näherung – zeigt, was eine Session im Mittel kostet")
    d.speichern("s08-sessions.json", szenario=True)


def s09():
    d = szenario("S09", "facade (Container-Limit 700 MB, -Xmx2500m)")
    cf = 'rolle="facade"'
    d.wert("Container: belegt/Limit", f"max(container_memory_working_set_bytes{{{cf}}}) / max(container_spec_memory_limit_bytes{{{cf}}})",
           "percentunit", schwellen=[(None, "green"), (0.85, "orange"), (0.95, "red")], beschreibung="cAdvisor – die Sicht, die das Limit kennt")
    d.wert("Swap", f"max(container_memory_swap{{{cf}}})", "bytes", schwellen=[(None, "green"), (1, "orange")],
           beschreibung="container_memory_swap – -m ohne --memory-swap erlaubt Swap in Höhe des Limits")
    d.wert("Heap belegt", f'sum(jvm_memory_used_bytes{{area="heap",{FACADE}}})', "bytes", beschreibung="jvm_memory_used_bytes{area=heap}")
    d.wert("Heap max (-Xmx)", f'sum(jvm_memory_max_bytes{{area="heap",{FACADE}}})', "bytes",
           schwellen=[(None, "orange")], beschreibung="größer als das Container-Limit")
    d.wert("Facade erreichbar", 'max(up{job="tomee-facade"}) or vector(0)', schwellen=[(None, "red"), (1, "green")],
           beschreibung="up – fällt beim OOM-Kill auf 0")
    d.wert("Neustarts (15 min)", 'sum(changes(process_start_time_seconds{job="tomee-facade"}[15m])) or vector(0)',
           schwellen=FEHLER_JE_MIN, beschreibung="process_start_time_seconds – der einzige JVM-Wert, der einen OOM-Kill verrät")

    d.zeile("Verlauf")
    d.kurve("Container-Speicher gegen Limit (cAdvisor)",
            [(f"max(container_memory_working_set_bytes{{{cf}}})", "belegt"),
             (f"max(container_memory_swap{{{cf}}})", "Swap"),
             (f"max(container_spec_memory_limit_bytes{{{cf}}})", "Limit")], "bytes", breite=12,
            beschreibung="container_memory_working_set_bytes, container_memory_swap, container_spec_memory_limit_bytes")
    d.kurve("JVM-Sicht: Heap belegt / max",
            [(f'sum(jvm_memory_used_bytes{{area="heap",{FACADE}}})', "belegt"),
             (f'sum(jvm_memory_max_bytes{{area="heap",{FACADE}}})', "max (-Xmx)"),
             (f"mes_szenario_gehaltenerheapmb{{{FACADE}}} * 1024 * 1024", "vom Szenario gehalten")], "bytes", breite=12,
            beschreibung="Aus Sicht der JVM ist noch reichlich Platz – kein OutOfMemoryError, sondern Exit 137")
    d.kurve("Erreichbarkeit und Neustarts",
            [('up{job="tomee-facade"}', "up"), ('changes(process_start_time_seconds{job="tomee-facade"}[5m])', "Neustarts (5 min)")],
            breite=12, beschreibung="up, process_start_time_seconds")
    d.kurve("GC-Zeitanteil", [(f"sum(rate(jvm_gc_collection_seconds_sum{{{FACADE}}}[1m]))", "facade")], "percentunit", breite=12,
            beschreibung="jvm_gc_collection_seconds_sum (rate) – bleibt ruhig, der GC sieht kein Problem")
    d.speichern("s09-facade.json", szenario=True)


def s10():
    d = szenario("S10", "fileprocessing (Limit 4096 File Descriptors, Socket-Ports 50000–50004)")
    d.wert("FD-Auslastung", f"jvm_os_open_file_descriptors{{{FP}}} / jvm_os_max_file_descriptors{{{FP}}}", "percentunit",
           schwellen=[(None, "green"), (0.7, "orange"), (0.85, "red")], beschreibung="OpenFileDescriptorCount / MaxFileDescriptorCount")
    d.wert("FDs offen", f"jvm_os_open_file_descriptors{{{FP}}}", beschreibung="jvm_os_open_file_descriptors")
    d.wert("FD-Limit", f"jvm_os_max_file_descriptors{{{FP}}}", beschreibung="jvm_os_max_file_descriptors")
    d.wert("Offene Dateien (Leck)", f"mes_szenario_offenedateien{{{FP}}}", beschreibung="mes_szenario_offenedateien")
    d.wert("Socket-Verbindungen", f"sum(mes_socket_offeneverbindungen{{{FP}}})", beschreibung="mes_socket_offeneverbindungen")
    d.wert("Socket abgelehnt (5 min)", f"sum(increase(mes_socket_abgelehnt_total{{{FP}}}[5m])) or vector(0)",
           schwellen=FEHLER_JE_MIN, beschreibung="mes_socket_abgelehnt_total")

    d.zeile("Verlauf")
    d.kurve("File Descriptors: offen / Limit",
            [(f"jvm_os_open_file_descriptors{{{FP}}}", "offen"), (f"jvm_os_max_file_descriptors{{{FP}}}", "Limit")], breite=12,
            beschreibung="440 gut? 500 gut? – erst das Verhältnis zum Limit sagt etwas")
    d.kurve("FD-Auslastung", [(f"jvm_os_open_file_descriptors{{{FP}}} / jvm_os_max_file_descriptors{{{FP}}}", "fileprocessing")],
            "percentunit", breite=12, max_wert=1, min_wert=0, schwellen=[(None, "green"), (0.7, "orange"), (0.85, "red")],
            beschreibung="Startwerte 70 % / 85 %")
    d.kurve("Wer hält die Descriptors?",
            [(f"mes_szenario_offenedateien{{{FP}}}", "offene Dateien (Leck)"),
             (f"sum(mes_socket_offeneverbindungen{{{FP}}})", "Socket-Verbindungen")],
            beschreibung="Jede Datei und jede Socket-Verbindung belegt einen Descriptor")
    d.kurve("SocketHandler-Pool",
            [(f'tomee_executor_poolsize{{executor="SocketHandler",{FP}}}', "Threads"),
             (f'tomee_executor_queuesize{{executor="SocketHandler",{FP}}}', "Queue"),
             (f"sum(mes_socket_wartendeverbindungen{{{FP}}})", "Verbindungen warten auf Thread")],
            beschreibung="tomee_executor_* für SocketHandler; mes_socket_wartendeverbindungen")
    d.kurve("Socket: angenommen / abgelehnt / Fehler pro Sekunde",
            [(f"sum(rate(mes_socket_angenommen_total{{{FP}}}[1m]))", "angenommen"),
             (f"sum(rate(mes_socket_abgelehnt_total{{{FP}}}[1m]))", "abgelehnt"),
             (f"sum(rate(mes_socket_verarbeitungsfehler_total{{{FP}}}[1m]))", "Fehler")], "ops",
            beschreibung="mes_socket_*_total – „Too many open files“ zeigt sich als Ablehnung/Fehler")
    d.speichern("s10-file-descriptors.json", szenario=True)


if __name__ == "__main__":
    ZIEL.mkdir(exist_ok=True)
    for alt in ZIEL.glob("*.json"):    # frühere Dashboards entfernen, Grafana löscht sie dann auch
        alt.unlink()
    jmx_dashboard()
    for erzeugen in (s01, s02, s03, s04, s05, s06, s07, s08, s09, s10):
        erzeugen()
