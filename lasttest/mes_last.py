#!/usr/bin/env python3
"""
mes_last.py – Last und geführte Störungsszenarien für die MES-Demo.

Nur Python-Standardbibliothek (ab 3.9), keine Installation nötig.

  python3 mes_last.py hilfe
  python3 mes_last.py status                       Live-Ampel aller Applikationsserver
  python3 mes_last.py szenario liste               alle Szenarien mit Kurzbeschreibung
  python3 mes_last.py szenario S01                 geführtes Szenario starten
  python3 mes_last.py szenario S01 -p buchen=200 -p dauer=60   mit eigenen Parametern
  python3 mes_last.py last --pfad /baugruppe/zufall/buchung --methode POST --parallel 50 --dauer 60
  python3 mes_last.py sockets --verbindungen 300 --halten 120
  python3 mes_last.py reset                        alle absichtlichen Störungen zurücknehmen

Weboberfläche für dieselben Szenarien: steuerung/ (Container mes-laststeuerung, Port 8070).
Ziel-Host mit --host (Standard: Umgebungsvariable MES_HOST oder localhost).
Strg+C beendet jedes Szenario und räumt auf.
"""

import argparse
import collections
import concurrent.futures
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
import types
import urllib.error
import urllib.parse
import urllib.request

# Ports wie beim Kunden (siehe docker-compose.yml); core2 nur mit ./start.sh --core2
ROLLEN = {"core": 8200, "fileprocessing": 8300, "singleton": 8100, "facade": 8400, "core2": 8201,
          "haproxy": 8090}
SOCKET_PORTS = range(50000, 50005)
HOST = os.environ.get("MES_HOST", "localhost")


# ─── HTTP ──────────────────────────────────────────────────────────────────

def url(rolle, pfad):
    return f"http://{HOST}:{ROLLEN[rolle]}/mes/api{pfad}"


def aufruf(rolle, pfad, methode="GET", timeout=180, params=None, daten=None):
    """Liefert (status, json|text). Netzwerkfehler → (0, Fehlertext). daten: Text im Body (POST)."""
    ziel = url(rolle, pfad)
    if params:
        ziel += ("&" if "?" in ziel else "?") + urllib.parse.urlencode(params)
    if daten is not None:
        anfrage = urllib.request.Request(ziel, method=methode, data=daten,
                                         headers={"Content-Type": "text/plain; charset=utf-8"})
    else:
        anfrage = urllib.request.Request(ziel, method=methode,
                                         data=b"" if methode in ("POST", "DELETE") else None)
    try:
        with urllib.request.urlopen(anfrage, timeout=timeout) as antwort:
            return antwort.status, _lesen(antwort.read())
    except urllib.error.HTTPError as e:
        return e.code, _lesen(e.read())
    except (urllib.error.URLError, OSError) as e:
        return 0, type(e).__name__ + ": " + str(getattr(e, "reason", e))


def _lesen(roh):
    try:
        return json.loads(roh)
    except ValueError:
        return roh.decode("utf-8", "replace")[:200]


def aktion(rolle, pfad, methode="POST", **params):
    status, inhalt = aufruf(rolle, pfad, methode, params=params)
    print(f"   → {methode} {rolle}{pfad} {params or ''}: HTTP {status} {kurz(inhalt)}")
    return inhalt


def kurz(inhalt):
    text = json.dumps(inhalt, ensure_ascii=False) if not isinstance(inhalt, str) else inhalt
    return text if len(text) < 160 else text[:157] + "..."


# ─── Lastgenerator ─────────────────────────────────────────────────────────

class Last:
    """Feuert Requests mit fester Parallelität, bis stop() gerufen wird."""

    def __init__(self, rolle, pfad, methode="GET", parallel=10, params=None, pause=0.0, name=None):
        self.rolle, self.pfad, self.methode = rolle, pfad, methode
        self.parallel, self.params, self.pause = parallel, params or {}, pause
        self.name = name or pfad
        self.ergebnisse = collections.Counter()
        self.dauer_summe = 0.0
        self.anzahl = 0
        self._stop = threading.Event()
        self._threads = []
        self._lock = threading.Lock()

    def start(self):
        for _ in range(self.parallel):
            t = threading.Thread(target=self._arbeiten, daemon=True)
            t.start()
            self._threads.append(t)
        return self

    def _arbeiten(self):
        while not self._stop.is_set():
            beginn = time.time()
            status, inhalt = aufruf(self.rolle, self.pfad, self.methode, params=self.params)
            # 503 ohne Fehlerart: Tomcat-Executor-Queue oder HAProxy voll
            schluessel = _schluessel(status, inhalt)
            with self._lock:
                self.ergebnisse[schluessel] += 1
                self.dauer_summe += time.time() - beginn
                self.anzahl += 1
            if self.pause or status == 0:
                # bei Netzwerkfehlern kurz warten, sonst dreht der Thread bei nicht erreichbarem Ziel leer
                self._stop.wait(self.pause or 0.2)

    def stop(self, warten=False):
        self._stop.set()
        if warten:
            for t in self._threads:
                t.join(timeout=5)

    def bericht(self):
        with self._lock:
            mittel = self.dauer_summe / self.anzahl if self.anzahl else 0
            teile = " ".join(f"{k}:{v}" for k, v in sorted(self.ergebnisse.items()))
        return f"{self.name} [{self.parallel}×] {teile or '-'} Ø {mittel:.2f}s"


def _schluessel(status, inhalt):
    """Ergebnis eines Requests für die Statistik: Status plus Fehlerart der Anwendung."""
    schluessel = str(status)
    if status >= 400 and isinstance(inhalt, dict) and "fehler" in inhalt:
        schluessel += " " + inhalt["fehler"]
    elif status == 503:
        schluessel += " abgewiesen"
    elif status == 0:
        schluessel = "Netzwerk"
    return schluessel


class RateLast:
    """Feuert Requests mit fester Rate – das offene Modell: Maschinen und das MES-Framework
    schicken im Takt, egal wie schnell die Antworten kommen. Werden die Antworten langsamer,
    steigt die Zahl gleichzeitig offener Requests (Little's Law: offen = Rate × Antwortzeit).
    Last mit festen Clients bremst sich dagegen selbst, sobald die Antworten langsamer werden."""

    def __init__(self, rolle, pfad, methode="GET", rate=10.0, params=None, name=None, max_offen=600,
                 daten=None):
        self.rolle, self.pfad, self.methode = rolle, pfad, methode
        self.rate, self.params, self.daten = max(0.1, float(rate)), params or {}, daten
        self.name, self.max_offen = name or pfad, max_offen
        self.ergebnisse = collections.Counter()
        self.dauern = collections.deque(maxlen=5000)
        self.offen = self.max_offen_gesehen = self.nicht_gesendet = 0
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self._pool = None

    def start(self):
        self._pool = concurrent.futures.ThreadPoolExecutor(max_workers=self.max_offen)
        threading.Thread(target=self._takt, daemon=True).start()
        return self

    def _takt(self):
        abstand = 1.0 / self.rate
        naechster = time.time()
        while not self._stop.is_set():
            jetzt = time.time()
            if jetzt < naechster:
                self._stop.wait(naechster - jetzt)
                continue
            # nach einem Hänger nicht mehr als 1 s nachholen
            naechster = max(naechster + abstand, jetzt - 1)
            with self._lock:
                if self.offen >= self.max_offen:
                    self.nicht_gesendet += 1
                    continue
                self.offen += 1
                self.max_offen_gesehen = max(self.max_offen_gesehen, self.offen)
            self._pool.submit(self._einer)

    def _einer(self):
        beginn = time.time()
        try:
            status, inhalt = aufruf(self.rolle, self.pfad, self.methode, params=self.params, daten=self.daten)
        except Exception as e:  # noqa: BLE001 – die Statistik soll jeden Fehler zählen
            status, inhalt = 0, str(e)
        with self._lock:
            self.ergebnisse[_schluessel(status, inhalt)] += 1
            self.dauern.append(time.time() - beginn)
            self.offen -= 1

    def stop(self, warten=False):
        self._stop.set()
        if self._pool:
            self._pool.shutdown(wait=warten, cancel_futures=True)

    def kennzahlen(self):
        with self._lock:
            dauern = sorted(self.dauern)
            gesamt = sum(self.ergebnisse.values())
            fehler = sum(v for k, v in self.ergebnisse.items() if not k.startswith("2"))
            return {"anzahl": gesamt, "fehler": fehler, "offen": self.offen, "maxOffen": self.max_offen_gesehen,
                    "mittel": sum(dauern) / len(dauern) if dauern else 0,
                    "p50": dauern[len(dauern) // 2] if dauern else 0,
                    "p95": dauern[min(len(dauern) - 1, int(len(dauern) * 0.95))] if dauern else 0,
                    "ergebnisse": dict(self.ergebnisse), "nichtGesendet": self.nicht_gesendet}

    def bericht(self):
        k = self.kennzahlen()
        teile = " ".join(f"{s}:{n}" for s, n in sorted(k["ergebnisse"].items()))
        extra = f" nicht gesendet {k['nichtGesendet']}" if k["nichtGesendet"] else ""
        return (f"{self.name} [{self.rate:g}/s] {teile or '-'} Ø {k['mittel']:.2f}s p95 {k['p95']:.2f}s "
                f"offen {k['offen']} (max {k['maxOffen']}){extra}")


# ─── Live-Status ───────────────────────────────────────────────────────────

def ampel(rolle):
    status, u = aufruf(rolle, "/diagnose/uebersicht", timeout=5)
    if status != 200 or not isinstance(u, dict):
        return f"{rolle:<15} nicht erreichbar (HTTP {status}) – Diagnose läuft über denselben Connector; JMX hilft weiter"
    http = next(iter(u.get("http", {}).values()), {})
    executor = next(iter(u.get("httpExecutor", {}).values()), None)
    if executor:
        # optimierte Konfig: Connector nutzt den Tomcat-Executor, der ThreadPool meldet maxThreads = -1
        http_text = (f"HTTP {executor.get('activeCount')}/{executor.get('maxThreads')}"
                     f" Q{executor.get('queueSize')}")
    else:
        http_text = f"HTTP {http.get('currentThreadsBusy', '?')}/{http.get('maxThreads', '?')}"
    teile = [f"{rolle:<15}", http_text]
    for name, werte in u.get("jdbcPool", {}).items():
        ds = name.split("DataSource=")[-1]
        if ds.startswith("Default"):
            continue
        kuerzel = "MES" if ds == "MES_Connection" else "MASTER"
        teile.append(f"{kuerzel} {werte.get('Active')}/{werte.get('MaxActive')} wart {werte.get('WaitCount')}")
    alt = [z for z in u.get("jdbcAnwendungssicht", []) if z.get("aeltesteAusleiheSekunden", 0) >= 5]
    if alt:
        teile.append("ältesteConn " + ",".join(f"{z['aeltesteAusleiheSekunden']:.0f}s" for z in alt))
    for name, werte in u.get("beanPools", {}).items():
        aktiv = werte.get("InstancesActive", 0)
        if aktiv or werte.get("AccessTimeouts"):
            bean = name.split("StatelessSessionBean=")[-1].split(",")[0]
            teile.append(f"{bean} {aktiv}/{werte.get('MaxSize')} TO {werte.get('AccessTimeouts')}")
    for name, werte in u.get("executoren", {}).items():
        if werte.get("activeCount") or werte.get("queueSize"):
            ex = name.split("name=")[-1]
            teile.append(f"{ex} T{werte.get('poolSize')} A{werte.get('activeCount')} Q{werte.get('queueSize')}")
    limit = next((w.get("InstanceLimit") for w in u.get("mdb", {}).values() if "InstanceLimit" in w), "?")
    for z in u.get("mdbAnwendungssicht", []):
        if z.get("aktiv"):
            teile.append(f"MDB {z['aktiv']}/{limit} Wartezeit {z.get('wartezeitSekunden', 0):.0f}s")
    log = u.get("logSammler", {})
    if log.get("queue") or log.get("wartendeAufrufer") or log.get("verworfen"):
        kap = log.get("kapazitaet", -1)
        teile.append(f"Log Q{log.get('queue')}{'/' + str(kap) if kap and kap > 0 else ''}"
                     f" Verzug {log.get('aeltesterEintragSekunden', 0):.0f}s wartend {log.get('wartendeAufrufer')}"
                     f" verworfen {log.get('verworfen')}")
    if u.get("wartung"):
        teile.append("WARTUNG")
    sched = []
    for name, werte in u.get("scheduler", {}).items():
        if "heartbeat" in name:
            art = "ejb" if "scheduler=ejb" in name else "quartz"
            sched.append(f"{art} {werte.get('SekundenSeitLetztemStart', 0):.0f}s")
        if "job=langlaeufer" in name and (werte.get("LaeuftGerade") or werte.get("Wartend") or werte.get("Laeufe")):
            teile.append(f"Langläufer läuft {werte.get('LaeuftGerade')} wartet {werte.get('Wartend')}"
                         f" übersprungen {werte.get('Uebersprungen')} Fehler {werte.get('Fehler')}")
    if sched:
        teile.append("Heartbeat " + " ".join(sched))
    tx = u.get("transaktionen", {})
    if tx.get("aktiv"):
        teile.append(f"TX {tx['aktiv']} (älteste {tx.get('aeltesteSekunden', 0):.0f}s)")
    fehler = next(iter(u.get("fehler", {}).values()), {})
    fehler = {k: v for k, v in fehler.items() if v}
    if fehler:
        teile.append("Fehler " + ",".join(f"{k}={v}" for k, v in fehler.items()))
    jvm = u.get("jvm", {})
    teile.append(f"Heap {jvm.get('heapBenutztMb')}/{jvm.get('heapMaxMb')}MB Thr {jvm.get('threads')}"
                 f" FD {jvm.get('offeneFileDescriptors')}/{jvm.get('maxFileDescriptors')}")
    if jvm.get("containerLimitMb"):
        teile.append(f"Container {jvm.get('containerBelegtMb')}/{jvm.get('containerLimitMb')}MB"
                     f" direct {jvm.get('directBufferMb', 0)}MB")
    return " | ".join(str(t) for t in teile)


def sperren_zeile():
    status, s = aufruf("singleton", "/diagnose/db-sperren", timeout=10)
    if status != 200:
        return "Oracle: nicht abfragbar"
    ketten = s.get("blockierketten", [])
    if not ketten:
        return "Oracle: keine Blockierung"
    blockiert = [k for k in ketten if k.get("blockiert_durch")]
    wurzeln = [k for k in ketten if not k.get("blockiert_durch")]
    wurzel = ", ".join(f"SID {w['sid']} {w['benutzer']}/{w.get('modul')}" for w in wurzeln[:2]) or "?"
    laengste = max((int(k.get("wartet_sekunden") or 0) for k in blockiert), default=0)
    return f"Oracle: {len(blockiert)} Sessions blockiert (längste {laengste}s) durch {wurzel}"


def _metriken(port, pfad="/metrics"):
    """Liest einen Prometheus-Endpunkt direkt: {(name, labels-text): wert}."""
    with urllib.request.urlopen(f"http://{HOST}:{port}{pfad}", timeout=5) as antwort:
        text = antwort.read().decode()
    werte = {}
    for zeile in text.splitlines():
        if zeile.startswith("#") or " " not in zeile:
            continue
        name_labels, wert = zeile.rsplit(" ", 1)
        name, _, labels = name_labels.partition("{")
        try:
            werte[(name, labels.rstrip("}"))] = float(wert)
        except ValueError:
            pass
    return werte


def haproxy_zeile():
    """Liest den HAProxy-Exporter direkt – funktioniert auch, wenn TomEE nicht mehr antwortet."""
    try:
        m = _metriken(8989)
    except OSError as e:
        return f"HAProxy: nicht erreichbar ({e})"
    sessions = m.get(("haproxy_backend_current_sessions", 'proxy="core"'), "?")
    queue = m.get(("haproxy_backend_current_queue", 'proxy="core"'), "?")
    server = []
    for (name, labels), wert in sorted(m.items()):
        if name == "haproxy_server_status" and wert == 1 and 'proxy="core"' in labels:
            srv = labels.split('server="')[1].split('"')[0]
            zustand = labels.split('state="')[1].split('"')[0]
            if zustand == "MAINT" and srv == "core2":
                continue  # core2 läuft nur mit ./start.sh --core2
            aktiv = m.get(("haproxy_server_current_sessions", f'proxy="core",server="{srv}"'), 0)
            server.append(f"{srv} {zustand} {aktiv:.0f}")
    fmt = lambda w: f"{w:.0f}" if isinstance(w, float) else w  # noqa: E731
    return (f"HAProxy core: Sessions {fmt(sessions)} Queue {fmt(queue)}"
            + (" | " + " · ".join(server) if len(server) > 1 else ""))


def jms_zeile(queue="MES.EINGANG"):
    """Broker-Sicht über den JMX Exporter im ActiveMQ-Container (:8886) – TomEE kennt die Queue-Tiefe nicht."""
    try:
        m = _metriken(8886)
    except OSError as e:
        return f"ActiveMQ: nicht erreichbar ({e})"
    def w(name, q=queue):
        return m.get((name, f'queue="{q}"'), 0)
    return (f"ActiveMQ {queue}: Tiefe {w('activemq_queue_queuesize'):.0f}"
            f" (davon in Zustellung {w('activemq_queue_inflightcount'):.0f})"
            f" · Konsumenten {w('activemq_queue_consumercount'):.0f}"
            f" · rein {w('activemq_queue_enqueuecount_total'):.0f} raus {w('activemq_queue_dequeuecount_total'):.0f}"
            f" · DLQ {w('activemq_queue_queuesize', 'ActiveMQ.DLQ'):.0f}")


def zeige_status(rollen, lasten=(), mit_sperren=False, mit_haproxy=False, mit_jms=False):
    zeit = time.strftime("%H:%M:%S")
    print(f"── {zeit} " + "─" * 60)
    for r in rollen:
        print("  " + ampel(r))
    if mit_sperren:
        print("  " + sperren_zeile())
    if mit_haproxy:
        print("  " + haproxy_zeile())
    if mit_jms:
        print("  " + jms_zeile())
    for last in lasten:
        print("  Last: " + last.bericht())


def beobachten(sekunden, rollen, lasten=(), mit_sperren=False, intervall=5, mit_haproxy=False, mit_jms=False):
    ende = time.time() + sekunden
    while time.time() < ende:
        zeige_status(rollen, lasten, mit_sperren, mit_haproxy, mit_jms)
        time.sleep(min(intervall, max(0, ende - time.time())))


# ─── Socket-Clients (FileProcessing) ───────────────────────────────────────

class SocketClients:
    def __init__(self, anzahl, datei_intervall=0.0, datei_kb=4):
        self.anzahl, self.datei_intervall, self.datei_kb = anzahl, datei_intervall, datei_kb
        self._stop = threading.Event()
        self.stat = collections.Counter()
        self._lock = threading.Lock()

    def start(self):
        for i in range(self.anzahl):
            threading.Thread(target=self._client, args=(i,), daemon=True).start()
        return self

    def _zaehlen(self, schluessel):
        with self._lock:
            self.stat[schluessel] += 1

    def _client(self, nummer):
        port = SOCKET_PORTS[nummer % len(SOCKET_PORTS)]
        try:
            with socket.create_connection((HOST, port), timeout=10) as s:
                s.settimeout(120)
                self._zaehlen("verbunden")
                datei = ("Zeile\n" * max(1, self.datei_kb * 170)).encode()
                while not self._stop.is_set():
                    if self.datei_intervall:
                        s.sendall(f"DATEI protokoll{nummer}.txt {len(datei)} STATION-{nummer % 12}\n".encode() + datei)
                        antwort = s.makefile().readline().strip()
                        self._zaehlen("OK" if antwort.startswith("OK") else antwort or "leer")
                        self._stop.wait(self.datei_intervall)
                    else:
                        self._stop.wait(1)
                s.sendall(b"ENDE\n")
        except OSError as e:
            self._zaehlen(type(e).__name__)

    def stop(self):
        self._stop.set()

    def bericht(self):
        with self._lock:
            return f"Sockets [{self.anzahl}] " + " ".join(f"{k}:{v}" for k, v in sorted(self.stat.items()))


# ─── Hilfen ────────────────────────────────────────────────────────────────

def reset(rollen=("core", "fileprocessing", "singleton", "core2")):
    for r in rollen:
        if r == "core2" and aufruf("core2", "/status", timeout=3)[0] == 0:
            continue  # core2 läuft nur mit ./start.sh --core2
        aktion(r, "/szenario/alle", "DELETE")


def hinweis(text):
    print("\n>>> " + text)


def container_zustand(name):
    if not shutil.which("docker"):
        return "(docker nicht verfügbar – auf der Demo-VM prüfen: docker inspect " + name + ")"
    try:
        aus = subprocess.run(["docker", "inspect", "-f",
                              "Status={{.State.Status}} OOMKilled={{.State.OOMKilled}} ExitCode={{.State.ExitCode}} Neustarts={{.RestartCount}}",
                              name], capture_output=True, text=True, timeout=10)
        return aus.stdout.strip() or aus.stderr.strip()
    except (OSError, subprocess.SubprocessError) as e:
        return str(e)


# ─── Parameter ─────────────────────────────────────────────────────────────
# Jedes Szenario beschreibt seine einstellbaren Werte selbst. Dieselbe Beschreibung
# nutzen die Kommandozeile (--param name=wert) und die Weboberfläche (steuerung/).

class P:
    """Ein einstellbarer Parameter. Der Typ ergibt sich aus dem Standardwert."""

    def __init__(self, name, text, standard, min=None, max=None, einheit="", hilfe="", auswahl=None):
        self.name, self.text, self.standard = name, text, standard
        self.min, self.max, self.einheit, self.hilfe, self.auswahl = min, max, einheit, hilfe, auswahl

    @property
    def typ(self):
        if self.auswahl:
            return "auswahl"
        if isinstance(self.standard, int):
            return "ganzzahl"
        if isinstance(self.standard, float):
            return "zahl"
        return "text"

    def wandeln(self, roh):
        """Wandelt einen Wert (Text oder Zahl) um und prüft die Grenzen. Fehler → ValueError."""
        try:
            if self.typ == "ganzzahl":
                wert = int(float(roh)) if not isinstance(roh, bool) else int(roh)
            elif self.typ == "zahl":
                wert = float(roh)
            else:
                wert = str(roh).strip()
        except (TypeError, ValueError):
            raise ValueError(f"{self.name}: '{roh}' ist keine gültige Zahl")
        if self.auswahl and wert not in self.auswahl:
            raise ValueError(f"{self.name}: erlaubt sind {', '.join(self.auswahl)}")
        if self.min is not None and wert < self.min:
            raise ValueError(f"{self.name}: mindestens {self.min}")
        if self.max is not None and wert > self.max:
            raise ValueError(f"{self.name}: höchstens {self.max}")
        return wert

    def als_dict(self):
        return {"name": self.name, "text": self.text, "standard": self.standard, "typ": self.typ,
                "min": self.min, "max": self.max, "einheit": self.einheit, "hilfe": self.hilfe,
                "auswahl": self.auswahl}


class Szenario:
    def __init__(self, funktion, modul, titel, beobachten, parameter, voraussetzung=""):
        self.funktion, self.modul, self.titel = funktion, modul, titel
        self.beobachten, self.parameter, self.voraussetzung = beobachten, parameter, voraussetzung

    def werte(self, roh=None):
        """Standardwerte, überschrieben durch roh (dict name → wert). Unbekannte Namen → ValueError."""
        roh = dict(roh or {})
        bekannt = {p.name: p for p in self.parameter}
        unbekannt = set(roh) - set(bekannt)
        if unbekannt:
            raise ValueError(f"unbekannte Parameter: {', '.join(sorted(unbekannt))} "
                             f"(erlaubt: {', '.join(bekannt) or 'keine'})")
        return types.SimpleNamespace(**{n: p.wandeln(roh[n]) if n in roh else p.standard
                                        for n, p in bekannt.items()})

    def als_dict(self, kennung):
        return {"id": kennung, "modul": self.modul, "titel": self.titel, "beobachten": self.beobachten,
                "voraussetzung": self.voraussetzung, "parameter": [p.als_dict() for p in self.parameter]}


def P_dauer(standard, text="Dauer"):
    return P("dauer", text, standard, 5, 3600, "s")


# ─── Szenarien ─────────────────────────────────────────────────────────────
# Zugeschnitten auf die Anforderungen des Kunden (kunde/Anforderungen-des-Kunden.md).
# Jede Funktion bekommt ihre Parameter als Namespace p (Werte siehe SZENARIEN unten).

def s01_tabellensperre(p):
    if p.ort == "master":
        hinweis("Die Replikation sperrt STAMMDATEN in der Master-DB. Dahinter stehen nur 20 Connections "
                "(Master_MES_Connection) bei 50 Beans. Beobachte, welcher Pool zuerst leer ist und welcher Fehler kommt.")
        tabelle, schreiben, lesen = "STAMMDATEN", "/stammdaten/schreiben", "/stammdaten/zufall"
    else:
        hinweis("Die Replikation sperrt BAUGRUPPE. Beobachte die Reihenfolge: Oracle → JDBC-Pool → Bean-Pool → HTTP → HAProxy.")
        tabelle, schreiben, lesen = "BAUGRUPPE", "/baugruppe/zufall/buchung", "/baugruppe/zufall"
    lasten = [Last("haproxy", schreiben, "POST", p.buchen, name="schreiben").start(),
              Last("haproxy", lesen, "GET", p.lesen, pause=0.2, name="lesen").start()]
    try:
        beobachten(p.vorlauf, ["core"], lasten, mit_haproxy=True)
        aktion("core", "/szenario/db/sperre", tabelle=tabelle, modus=p.modus, sekunden=p.dauer)
        if p.ort == "master":
            hinweis("Frage: Warum steigt hier WaitCount, bei der lokalen Sperre aber nicht? Und warum kommt der Fehler "
                    "jetzt als PoolErschoepft? Beim Kunden trifft diese Sperre alle Länder zugleich.")
        else:
            hinweis("Frage: Welche Metrik reagiert zuerst? Oracle-Leser warten nie auf Sperren – warum scheitern die Lese-Requests nach 30 s trotzdem?")
        beobachten(p.dauer, ["core", "singleton"], lasten, mit_sperren=True, mit_haproxy=True)
        hinweis("Sperre ist abgelaufen – Erholung beobachten.")
        beobachten(p.nachlauf, ["core"], lasten)
    finally:
        [l.stop() for l in lasten]
        aktion("core", "/szenario/db/sperre", "DELETE")


def s02_verbindungen_voll(p):
    hinweis(f"{p.parallel} langsame Abfragen ({p.sekunden} s) gegen {p.datasource}. Keine Sperre – nur Laufzeit.")
    last = Last("core", "/szenario/db/langsam", "GET", p.parallel,
                params={"sekunden": p.sekunden, "datasource": p.datasource}, name="langsam").start()
    abgleich = Last("core", "/stammdaten/abgleich", "POST", p.abgleich, pause=1, name="abgleich").start()
    try:
        hinweis("Nach 30 s: PoolExhaustedException – maxWaitTime=-1 wirkt NICHT als 'unbegrenzt'.")
        beobachten(p.dauer, ["core"], [last, abgleich])
    finally:
        last.stop()
        abgleich.stop()


def s03_beanpool_leer(p):
    hinweis(f"Langsame Bean ohne Datenbank: {p.parallel} Aufrufer, 50 Beans (Kunde). "
            "Wer keine Bean bekommt, wartet accessTimeout (Kunde 30 s) und bekommt dann einen Fehler.")
    last = Last("core", "/szenario/bean/langsam", "GET", p.parallel, params={"ms": p.ms}, name="bean langsam").start()
    try:
        beobachten(p.dauer, ["core"], [last], intervall=5)
    finally:
        last.stop()


def s04_http_threads(p):
    hinweis(f"{p.parallel} parallele langsame Requests ({p.ms} ms) über HAProxy (maxconn 200 je Server).")
    last = Last("haproxy", "/szenario/http/langsam", "GET", p.parallel, params={"ms": p.ms}, name="http langsam").start()
    try:
        hinweis("HTTP-Threads am Limit, CPU niedrig. Die Diagnose über HTTP fällt mit aus – "
                "HAProxy-Statistik (:8989) und JConsole (:9200) funktionieren weiter.")
        beobachten(p.dauer, ["core"], [last], mit_haproxy=True)
    finally:
        last.stop()


def _zahlenliste(text, name):
    try:
        werte = [int(x) for x in text.replace(";", ",").split(",") if x.strip()]
    except ValueError:
        raise ValueError(f"{name}: kommagetrennte Ganzzahlen erwartet, z. B. 100,900,100,400")
    if not werte or any(w < 1 or w > 20000 for w in werte):
        raise ValueError(f"{name}: jeder Wert zwischen 1 und 20000")
    return werte


def s05_executor(p):
    schritte = _zahlenliste(p.schritte, "schritte")
    standardfall = p.executor == "BatchHandling" and schritte == [100, 900, 100, 400]
    hinweis(f"{p.executor}: Aufgaben in Schritten {schritte}, je {p.dauer} s Laufzeit."
            + (" Core 100, Queue 1000, Max 10000. Wann entsteht Thread 101?" if standardfall else ""))
    for schritt, anzahl in enumerate(schritte, 1):
        aktion("singleton", f"/szenario/executor/{p.executor}", aufgaben=anzahl, ms=p.dauer * 1000)
        zeige_status(["singleton"])
        if standardfall and schritt == 2:
            hinweis("1000 Aufgaben: immer noch 100 Threads, 900 in der Queue. Jetzt 100 mehr (Queue voll) …")
        if standardfall and schritt == 3:
            hinweis("… und jetzt 400 weitere: Jede Aufgabe über der Queue erzeugt einen neuen Thread.")
        time.sleep(p.pause)
    beobachten(p.dauer, ["singleton"], intervall=10)


def s06_timer_tickt_nicht(p):
    if p.ursache == "sperre":
        hinweis("Kundenfall: Der Stammdatenabgleich (EJB-Timer und Quartz, jede Minute) hängt an einer Tabellensperre.")
        aktion("core", "/szenario/db/sperre", tabelle="BAUGRUPPE", sekunden=p.dauer)
        hinweis("Jede Minute hängt ein weiterer Abgleich. Nach 3 Läufen sind alle 3 EJB-Timer-Threads belegt – "
                "danach tickt auch der Heartbeat nicht mehr. Kein Fehler, keine Exception.")
        try:
            beobachten(p.dauer, ["singleton"], mit_sperren=True, intervall=15)
        finally:
            aktion("core", "/szenario/db/sperre", "DELETE")
        hinweis("Sperre weg: Die hängenden Läufe kommen zurück, der Heartbeat läuft wieder.")
    else:
        hinweis(f"{p.anzahl} lange Läufe belegen die Threads des {p.timer.upper()}-Schedulers "
                "(EJB: openejb.timer.pool.size, Default 3; Quartz: QUARTZ_THREADS, Demo 5).")
        aktion("singleton", "/szenario/scheduler/blockieren", art=p.timer, anzahl=p.anzahl, sekunden=p.dauer)
        hinweis("Der Heartbeat (alle 10 s) läuft nicht mehr – kein Fehler, keine Exception, einfach Stille.")
        beobachten(p.dauer, ["singleton"], intervall=10)
    beobachten(p.nachlauf, ["singleton"], intervall=10)
    status, s = aufruf("singleton", "/szenario/scheduler")
    for job in s.get("jobs", []) if isinstance(s, dict) else []:
        print(f"   {job['scheduler']:<7} {job['job']:<20} Misfires {job['misfires']} "
              f"max. Verspätung {job['maxVerspaetungMs']} ms")


def s07_transaktion(p):
    timeout_text = f"{p.timeout} s Timeout" if p.timeout else "Default-Timeout des TX-Managers"
    hinweis(f"Lange Transaktion ({p.sekunden} s, {timeout_text}) sperrt Baugruppe {p.sperre_id}. "
            f"Buchungen auf {p.sperre_id} hängen.")
    ergebnis = {}
    t = threading.Thread(target=lambda: ergebnis.update(
        wert=aufruf("core", "/szenario/tx/lang", params={"sekunden": p.sekunden, "timeout": p.timeout,
                                                          "sperreId": p.sperre_id})), daemon=True)
    t.start()
    time.sleep(2)
    last = Last("core", f"/baugruppe/{p.sperre_id}/buchung", "POST", p.buchungen, name=f"buchen id {p.sperre_id}").start()
    try:
        hinweis(f"Der Timeout bricht die Arbeit NICHT ab – die Sperre hält bis Methodenende ({p.sekunden} s). "
                "Ab TX_WARN_SEKUNDEN (Demo 60 s) steht die Transaktion im Log.")
        beobachten(p.sekunden + 10, ["core"], [last], mit_sperren=True, intervall=10)
        t.join(timeout=30)
        print("   Ergebnis der langen Transaktion:", kurz(ergebnis.get("wert")))
        hinweis("Ohne Timeout gilt der Default der Kundenkonfiguration: 14400 s. "
                "Die TomEE-MBean zeigt trotzdem '10 MINUTES' (siehe /mes/api/diagnose/konfig).")
    finally:
        last.stop()


def s08_sessions(p):
    hinweis(f"Clients ohne Cookie: jeder Request legt eine neue HTTP-Session ({p.kb} KB) an. Timeout 30 min.")
    last = Last("core", "/szenario/session/anlegen", "GET", p.parallel, params={"kb": p.kb}, name="sessions").start()
    try:
        beobachten(p.dauer, ["core"], [last], intervall=10)
        hinweis("tomcat_sessions_activesessions steigt, der Heap ebenso – und bleibt 30 min so.")
    finally:
        last.stop()


def s09_facade_grenzen(p):
    hinweis("Facade: -Xmx2500m bei 700 MB Container-Limit (Kunde: 7168 MB bei 2000 MB). "
            "Voraussetzung: ./start.sh kunde --facade")
    for _ in range(p.schritte):
        status, inhalt = aufruf("facade", "/szenario/jvm/leck", "POST", params={"mb": p.schritt_mb})
        print(f"   +{p.schritt_mb} MB Heap: HTTP {status} {kurz(inhalt)}")
        if status == 0:
            break
        time.sleep(p.pause)
    time.sleep(3)
    print("   Container:", container_zustand("mes-facade"))
    hinweis("Kein OutOfMemoryError im Log – der Kernel hat den Prozess beendet (Exit 137). Die JVM kann das nicht melden. "
            "Sichtbar nur von außen: Neustart-Zähler in docker inspect (OOMKilled wird beim Neustart zurückgesetzt), "
            "docker events --filter event=oom, up == 0, neue process_start_time_seconds. "
            "Dass mehr als 700 MB belegt werden konnten, liegt am Swap: docker run -m ohne --memory-swap "
            "erlaubt zusätzlich Swap in Höhe des Limits.")


def s10_file_descriptors(p):
    hinweis(f"FileProcessing (Limit 4096 FDs): Datei-Leck in {p.schritt}er-Schritten plus {p.clients} offene Socket-Verbindungen.")
    clients = SocketClients(p.clients).start()
    try:
        for _ in range(p.schritte):
            aktion("fileprocessing", "/szenario/jvm/dateien", anzahl=p.schritt)
            zeige_status(["fileprocessing"])
            print("  " + clients.bericht())
            time.sleep(5)
        hinweis("440 gut? 500 gut? – Verhältnis zum Limit, Trend, Verhalten nach der Last.")
        beobachten(p.nachlauf, ["fileprocessing"], intervall=10)
    finally:
        clients.stop()
        aktion("fileprocessing", "/szenario/jvm/dateien", "DELETE")


def s11_intervall(p):
    hinweis(f"Ein periodischer Job alle {p.intervall} s braucht {p.laufzeit} s – länger als sein Intervall. "
            f"Überlappungsschutz: {p.schutz}. Alle EJB-Timer der JVM teilen sich 3 Threads (openejb.timer.pool.size).")
    if p.schutz == "ohne":
        belegt = math.ceil(p.laufzeit / p.intervall)
        hinweis(f"Ohne Schutz überlappen die Läufe: {p.laufzeit} ÷ {p.intervall} ≈ {belegt} Timer-Threads dauerhaft belegt"
                + (" – mehr als es gibt. Der Heartbeat bekommt keinen Thread mehr." if belegt >= 3 else "."))
    elif p.schutz == "singleton-lock":
        hinweis("Die Arbeit steckt in einem @Singleton mit Default-Sperre (WRITE): Fällige Läufe warten auf die Sperre "
                "– bis zu 30 s (AccessTimeout) – und halten dabei ihren Timer-Thread. Danach: ConcurrentAccessTimeoutException.")
    else:
        hinweis("Mit Überlappungsschutz entfällt ein Termin, solange der vorige Lauf noch arbeitet – ein Thread, ein Lauf.")
    aktion("singleton", "/szenario/scheduler/langlaeufer", intervall=p.intervall, laufzeit=p.laufzeit, schutz=p.schutz)
    try:
        beobachten(p.dauer, ["singleton"], intervall=10)
    finally:
        aktion("singleton", "/szenario/scheduler/langlaeufer", "DELETE")
    hinweis("Keine neuen Läufe mehr – laufende arbeiten zu Ende, dann tickt der Heartbeat wieder.")
    beobachten(p.nachlauf, ["singleton"], intervall=10)
    status, s = aufruf("singleton", "/szenario/scheduler")
    for job in s.get("jobs", []) if isinstance(s, dict) else []:
        if job["scheduler"] == "ejb" and job["job"] in ("heartbeat", "langlaeufer"):
            print(f"   ejb {job['job']:<12} Läufe {job['laeufe']} übersprungen {job['uebersprungen']} "
                  f"Fehler {job['fehler']} max. Verspätung {job['maxVerspaetungMs']} ms")


class Sender:
    """Schickt jede Sekunde `rate` Nachrichten an die Queue (über den Core, der sie per JMS weiterreicht)."""

    def __init__(self, rate, art, ms, gift):
        self.parameter = {"anzahl": rate, "art": art, "ms": ms, "gift": gift}
        self.gesendet = self.fehler = 0
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._senden, daemon=True).start()
        return self

    def _senden(self):
        naechster = time.time()
        while not self._stop.is_set():
            status, inhalt = aufruf("core", "/szenario/jms/senden", "POST", timeout=30, params=self.parameter)
            if status == 200:
                self.gesendet += self.parameter["anzahl"]
            else:
                self.fehler += 1
            naechster += 1
            self._stop.wait(max(0, naechster - time.time()))

    def stop(self):
        self._stop.set()

    def bericht(self):
        return f"Sender [{self.parameter['anzahl']}/s {self.parameter['art']}] gesendet {self.gesendet}" + (
            f" Fehler {self.fehler}" if self.fehler else "")


def s12_nachrichten(p):
    art = "buchung" if p.ursache == "sperre" else "langsam"
    gift = p.gift_prozent if p.ursache == "gift" else 0
    if art == "langsam":
        kapazitaet = 10 / max(p.ms / 1000, 0.001)
        hinweis(f"{p.rate} Nachrichten/s an MES.EINGANG, Verarbeitung je {p.ms} ms. Der Core verarbeitet höchstens 10 "
                f"gleichzeitig (Default MDB Container: InstanceLimit 10) – also höchstens {kapazitaet:.0f}/s."
                + (f" {gift} % der Nachrichten scheitern immer (Gift)." if gift else ""))
    else:
        hinweis(f"{p.rate} Nachrichten/s, jede bucht auf BAUGRUPPE. Die Replikation sperrt die Tabelle – "
                "alle 10 MDB-Instanzen hängen in Oracle.")
        aktion("core", "/szenario/db/sperre", tabelle="BAUGRUPPE", sekunden=p.dauer)
    sender = Sender(p.rate, art, p.ms, gift).start()
    try:
        beobachten(p.dauer, ["core"], [sender], mit_jms=True, mit_sperren=p.ursache == "sperre", intervall=10)
        sender.stop()
        if p.ursache == "sperre":
            aktion("core", "/szenario/db/sperre", "DELETE")
        hinweis("Keine neuen Nachrichten mehr – der Rückstand wird abgebaut. Dauer ≈ Tiefe ÷ Durchsatz.")
        beobachten(p.nachlauf, ["core"], [sender], mit_jms=True, intervall=10)
    finally:
        sender.stop()
        aktion("core", "/szenario/db/sperre", "DELETE")
        hinweis("Rest der Queue und die Dead Letter Queue werden geleert.")
        aktion("core", "/szenario/jms", "DELETE")


def s13_wartung(p):
    if aufruf("core2", "/status", timeout=5)[0] == 0:
        print("   core2 ist nicht erreichbar (Port 8201). Voraussetzung: ./start.sh kunde --core2")
        return
    gleichzeitig = p.rate * p.ms / 1000
    hinweis(f"{p.rate} Requests/s über HAProxy, je {p.ms} ms → im Mittel {gleichzeitig:.0f} gleichzeitig "
            f"(Little's Law). Auf zwei Cores je {gleichzeitig / 2:.0f} von 50 Beans ({gleichzeitig / 100:.0%}), "
            f"auf einem allein {gleichzeitig:.0f} von 50 ({gleichzeitig / 50:.0%}).")
    last = RateLast("haproxy", "/szenario/bean/langsam", "GET", p.rate, params={"ms": p.ms}, name="über HAProxy").start()
    rollen = ["core", "core2"]
    try:
        beobachten(p.vorlauf, rollen, [last], mit_haproxy=True)
        aktion(p.server, "/szenario/wartung", "POST")
        hinweis(f"{p.server} geht in Wartung: /mes/api/status antwortet 503. HAProxy nimmt ihn nach 3 Fehlversuchen "
                "(ca. 15 s) heraus, laufende Requests laufen zu Ende – dann trägt der andere alles.")
        beobachten(p.dauer, rollen, [last], mit_haproxy=True)
        aktion(p.server, "/szenario/wartung", "DELETE")
        hinweis("Freigabe: nach 2 erfolgreichen Checks (ca. 10 s) bekommt der Server wieder Last.")
        beobachten(p.nachlauf, rollen, [last], mit_haproxy=True)
    finally:
        last.stop()
        aktion(p.server, "/szenario/wartung", "DELETE")
    k = last.kennzahlen()
    print(f"   Gesamt: {k['anzahl']} Requests, {k['fehler']} Fehler, p95 {k['p95']:.2f} s, max. {k['maxOffen']} gleichzeitig offen")


def _container(rolle):
    status, u = aufruf(rolle, "/diagnose/uebersicht", timeout=10)
    jvm = u.get("jvm", {}) if isinstance(u, dict) else {}
    return jvm.get("containerBelegtMb"), jvm.get("containerLimitMb"), jvm


def s14_speicher(p):
    hinweis("Singleton: -Xmx1024m bei 1150 MB Container-Limit (Kunde: -Xms4048M -Xmx4500M bei -m 5000m) – der Heap "
            "darf fast alles haben. Jetzt wächst, was NICHT im Heap liegt: Threads (Stack) und Direct Buffer.")
    try:
        for schritt in range(1, p.schritte + 1):
            belegt, limit, jvm = _container("singleton")
            if belegt and limit and belegt / limit >= p.ziel_prozent / 100:
                hinweis(f"Ziel {p.ziel_prozent} % erreicht ({belegt}/{limit} MB) – keine weiteren Schritte.")
                break
            if p.threads_je_schritt:
                aktion("singleton", "/szenario/jvm/threads", anzahl=p.threads_je_schritt, stackKb=p.stack_kb,
                       sekunden=3600)
            if p.offheap_mb_je_schritt:
                aktion("singleton", "/szenario/jvm/offheap", mb=p.offheap_mb_je_schritt)
            time.sleep(2)
            belegt, limit, jvm = _container("singleton")
            print(f"   Schritt {schritt}: Container {belegt}/{limit} MB · Heap {jvm.get('heapBenutztMb')}/"
                  f"{jvm.get('heapMaxMb')} MB · Threads {jvm.get('threads')} · Direct Buffer {jvm.get('directBufferMb')} MB")
            time.sleep(p.pause)
        hinweis("Heap unauffällig, Container am Limit. Threads und Direct Buffer zeigt JMX als Zahl, ihren Speicher "
                "nur die Container-Sicht (cAdvisor, java.lang:type=OperatingSystem TotalMemorySize/FreeMemorySize) "
                "oder Native Memory Tracking. Wird das Limit überschritten, beendet der Kernel den Prozess (Exit 137).")
        beobachten(p.halten, ["singleton"], intervall=10)
    finally:
        aktion("singleton", "/szenario/jvm/threads", "DELETE")
        aktion("singleton", "/szenario/jvm/offheap", "DELETE")


def s15_sitzungsgrenze(p):
    if p.grenze == "benutzer":
        hinweis(f"Oracle erlaubt MES_LOCAL höchstens {p.limit} gleichzeitige Sessions (Profil, SESSIONS_PER_USER). "
                f"Core und FileProcessing öffnen je {p.parallel} langsame Abfragen – jeder Pool hat 50 Plätze.")
        aktion("core", "/szenario/db/sitzungslimit", benutzer="MES_LOCAL", limit=p.limit)
    else:
        hinweis(f"Keine künstliche Grenze: Core, FileProcessing und Singleton öffnen je {p.parallel} langsame Abfragen. "
                "Oracle Free erlaubt 200 Prozesse, rund 90 belegt die Datenbank selbst.")
    rollen = ["core", "fileprocessing"] + (["singleton"] if p.grenze == "prozesse" else [])
    lasten = [Last(r, "/szenario/db/langsam", "GET", p.parallel,
                   params={"sekunden": p.sekunden, "datasource": "MES_Connection"}, name=f"{r} langsam").start()
              for r in rollen]
    try:
        hinweis("Wer über der Grenze eine Connection öffnen will, bekommt SOFORT einen Fehler – nicht nach 30 s, "
                "und obwohl sein eigener Pool noch Luft hat.")
        beobachten(p.dauer, rollen, lasten, mit_sperren=True, intervall=10)
    finally:
        for last in lasten:
            last.stop()
        aktion("core", "/szenario/db/sitzungslimit", "DELETE")
    hinweis("Rechnung für den Kunden: Summe aller maxActive über alle Container und Applikationsserver gegen "
            "processes/sessions der Datenbank – und bei der Master-DB über alle Länder.")


def s16_kundenprofil(p):
    rate = 81 * p.faktor
    log_rate = rate * p.log_anteil / 100
    fach = rate - log_rate
    hinweis(f"Kundenprofil: 7 Mio. Requests/Tag ≈ 81/s, davon {p.log_anteil} % Logeinträge. Faktor {p.faktor:g} → "
            f"{rate:.0f}/s ({fach:.0f} fachlich, {log_rate:.0f} Log) über HAProxy, dazu Dateien per TCP "
            f"(20 000/Tag ≈ {0.23 * p.faktor:.2f}/s).")
    text = ("Protokoll " + "x" * 200).encode()
    lasten = [RateLast("haproxy", "/baugruppe/zufall", "GET", fach * 0.7, name="lesen").start(),
              RateLast("haproxy", "/baugruppe/zufall/buchung", "POST", fach * 0.3, name="buchen").start(),
              RateLast("haproxy", "/log", "POST", max(log_rate, 0.1), name="log", daten=text).start()]
    dateien = SocketClients(1, datei_intervall=1 / (0.23 * p.faktor)).start() if p.dateien == "ja" else None
    spitzen = collections.defaultdict(float)
    try:
        ende = time.time() + p.dauer
        while time.time() < ende:
            zeige_status(["core"], lasten)
            if dateien:
                print("  " + dateien.bericht())
            status, u = aufruf("core", "/diagnose/uebersicht", timeout=5)
            if status == 200:
                http = next(iter(u.get("http", {}).values()), {})
                spitzen["HTTP-Threads belegt"] = max(spitzen["HTTP-Threads belegt"], http.get("currentThreadsBusy", 0))
                for name, werte in u.get("jdbcPool", {}).items():
                    ds = name.split("DataSource=")[-1]
                    if not ds.startswith("Default"):
                        spitzen[f"{ds} aktiv"] = max(spitzen[f"{ds} aktiv"], werte.get("Active", 0))
                for name, werte in u.get("beanPools", {}).items():
                    bean = name.split("StatelessSessionBean=")[-1].split(",")[0]
                    spitzen[f"Bean {bean} aktiv"] = max(spitzen[f"Bean {bean} aktiv"], werte.get("InstancesActive", 0))
                spitzen["Log-Queue"] = max(spitzen["Log-Queue"], u.get("logSammler", {}).get("queue", 0))
            time.sleep(min(10, max(0, ende - time.time())))
    finally:
        for last in lasten:
            last.stop()
        if dateien:
            dateien.stop()
    print("\n   Baseline – Spitzenwerte während des Laufs (Momentaufnahmen alle 10 s):")
    for name, wert in spitzen.items():
        print(f"     {name:<32} {wert:.0f}")
    print("\n   Antwortzeiten je Anfrageart:")
    for last in lasten:
        k = last.kennzahlen()
        print(f"     {last.name:<8} {last.rate:6.1f}/s  Ø {k['mittel'] * 1000:6.0f} ms  p95 {k['p95'] * 1000:6.0f} ms  "
              f"Fehler {k['fehler']}  gleichzeitig offen max. {k['maxOffen']}")
    hinweis("Little's Law: gleichzeitig belegt ≈ Rate × Antwortzeit. Daraus die Startwerte: Warnstufe dort, wo die "
            "Spitze mit Reserve liegt – und bei zwei Applikationsservern so, dass einer allein die Last trägt (S13).")


def s17_logflut(p):
    hinweis(f"Log-Flut: {p.rate} Logeinträge/s à {p.groesse_kb} KB (z. B. Debug-Logging an oder Fehlerkaskade). "
            f"Der Schreiber schafft nur {p.schreiblimit} Zeilen/s (langsame Platte, gebremster Agent). "
            f"Queue-Verhalten: {p.modus}.")
    aktion("core", "/szenario/log", modus=p.modus, kapazitaet=p.kapazitaet, schreibLimit=p.schreiblimit)
    text = ("Stacktrace " + "x" * max(0, p.groesse_kb * 1024 - 11)).encode()
    lasten = [RateLast("haproxy", "/log", "POST", p.rate, name="log", daten=text).start(),
              RateLast("haproxy", "/baugruppe/zufall", "GET", p.fachlich, name="fachlich").start()]
    try:
        beobachten(p.dauer, ["core"], lasten, mit_haproxy=True, intervall=10)
    finally:
        for last in lasten:
            last.stop()
    hinweis("Log-Flut vorbei – der Schreiber holt den Rückstand auf (Verzug = ältester Eintrag).")
    try:
        beobachten(p.nachlauf, ["core"], intervall=10)
    finally:
        aktion("core", "/szenario/log", "DELETE")


def s18_leck(p):
    hinweis(f"Ein Codepfad gibt Connections nicht zurück: alle {p.intervall} s {p.anzahl} Stück aus {p.datasource}. "
            "Dazu normale Lesezugriffe. Beobachte den Pool – und in Oracle den Zustand der Sessions.")
    lesen = Last("core", "/baugruppe/zufall", "GET", p.lesen, pause=0.2, name="lesen").start()
    try:
        ende = time.time() + p.dauer
        while time.time() < ende:
            aktion("core", "/szenario/db/leck", datasource=p.datasource, anzahl=p.anzahl)
            zeige_status(["core"], [lesen], mit_sperren=False)
            print("  " + oracle_sitzungen_zeile())
            time.sleep(min(p.intervall, max(0, ende - time.time())))
        hinweis("Kunde: removeAbandoned = true, Timeout 3600 s (MES_Connection) bzw. removeAbandoned = false (Master) – "
                "das Leck bleibt eine Stunde oder für immer. Optimiert: suspectTimeout 60 s (Log-Warnung), Abräumen nach 600 s.")
        beobachten(p.halten, ["core"], [lesen], intervall=10)
    finally:
        lesen.stop()
        aktion("core", "/szenario/db/leck", "DELETE")


def oracle_sitzungen_zeile():
    """Sessions je DB-User aus Sicht von Oracle (aktiv = Statement läuft, inaktiv = wartet auf den Client)."""
    status, u = aufruf("singleton", "/diagnose/mbeans", timeout=10,
                       params={"muster": "mes.demo:type=OracleSitzungen,*", "attribute": "true"})
    if status != 200 or not isinstance(u, dict):
        return "Oracle-Sessions: nicht abfragbar"
    teile = []
    for name, w in sorted(u.items()):
        if w.get("Gesamt"):
            grenze = f" Grenze {w['Limit']}" if w.get("Limit", -1) >= 0 else ""
            teile.append(f"{w.get('Benutzer')} {w['Gesamt']} (aktiv {w['Aktiv']}, inaktiv {w['Inaktiv']}){grenze}")
    return "Oracle-Sessions: " + (" · ".join(teile) or "keine")


def s19_gc(p):
    hinweis(f"Core: Heap-Leck von {p.leck_mb} MB (Serial GC: Old Gen fasst etwa 2/3 von -Xmx), dazu {p.muell_rate} "
            f"Requests/s, die je {p.muell_kb} KB kurzlebigen Müll erzeugen, und normale Lesezugriffe.")
    lasten = [RateLast("core", "/baugruppe/zufall", "GET", p.lese_rate, name="lesen").start()]
    try:
        beobachten(p.vorlauf, ["core"], lasten, intervall=10)
        geleckt = 0
        while geleckt < p.leck_mb:
            schritt = min(p.schritt_mb, p.leck_mb - geleckt)
            aktion("core", "/szenario/jvm/leck", mb=schritt)
            geleckt += schritt
        lasten.append(RateLast("core", "/szenario/jvm/muell", "GET", p.muell_rate, params={"kb": p.muell_kb},
                               name="Müll").start())
        hinweis("Die Old Gen ist fast voll: Jede Garbage Collection findet kaum noch etwas. Beobachte den GC-Anteil, "
                "den Heap NACH der GC und die Antwortzeit der Lesezugriffe.")
        beobachten(p.dauer, ["core"], lasten, intervall=10)
    finally:
        for last in lasten:
            last.stop()
        aktion("core", "/szenario/jvm/leck", "DELETE")
    hinweis("Leck freigegeben – nach der nächsten vollen GC ist der Heap wieder leer, die Antwortzeiten normal.")
    beobachten(p.nachlauf, ["core"], intervall=10)


# Kundenthema aus kunde/Anforderungen-des-Kunden.md, Abschnitte 2–4
SPERRMODUS = ["tabelle", "zeilen"]
EXECUTOREN = ["BatchHandling", "MslHandling", "GeneralThreadPool", "FileWatcher", "SocketHandler"]
DATENQUELLEN = ["Master_MES_Connection", "MES_Connection"]

SZENARIEN = {
    "S01": Szenario(s01_tabellensperre, "Gelockte Tabelle (WICHTIGSTE)",
                    "Tabelle durch Replikation gesperrt – Pools laufen leer",
                    "Oracle blockiert → JDBC-Pool 50/50 → BaugruppeService 50/50 → HTTP-Threads → nach 30 s BEAN_POOL_TIMEOUT, auch für Leser. "
                    "Mit ort = master: Master-Pool 20/20, WaitCount steigt, PoolErschoepft.", [
                        P("ort", "Wo sperrt die Replikation?", "lokal", auswahl=["lokal", "master"],
                          hilfe="lokal = BAUGRUPPE (MES_Connection, 50), master = STAMMDATEN in der Master-DB (Master_MES_Connection, 20)"),
                        P("buchen", "Schreibende Clients", 150, 0, 2000),
                        P("lesen", "Lesende Clients", 5, 0, 500),
                        P("modus", "Sperre", "tabelle", auswahl=SPERRMODUS, hilfe="tabelle = LOCK TABLE, zeilen = alle Zeilen FOR UPDATE"),
                        P("vorlauf", "Vorlauf ohne Sperre", 20, 0, 600, "s"),
                        P_dauer(120, "Dauer der Sperre"),
                        P("nachlauf", "Erholung beobachten", 30, 0, 600, "s")]),
    "S02": Szenario(s02_verbindungen_voll, "DB-Verbindungen",
                    "DB-Verbindungen laufen voll",
                    "Master 20/20, WaitCount steigt, nach 30 s PoolExhaustedException (maxWaitTime = -1 wirkt nicht).", [
                        P("parallel", "Parallele Abfragen", 40, 1, 1000),
                        P("sekunden", "Laufzeit je Abfrage", 45, 1, 3600, "s"),
                        P("datasource", "DataSource", "Master_MES_Connection", auswahl=DATENQUELLEN),
                        P("abgleich", "Clients Stammdatenabgleich", 2, 0, 100),
                        P_dauer(90)]),
    "S03": Szenario(s03_beanpool_leer, "Bean-Pools",
                    "Bean-Pool leer („50 Beans pro Fassade“)",
                    "InstancesActive 50/50, nach accessTimeout AccessTimeouts / BEAN_POOL_TIMEOUT.", [
                        P("parallel", "Aufrufer", 80, 1, 1000),
                        P("ms", "Laufzeit je Aufruf", 40000, 1, 600000, "ms"),
                        P_dauer(60)]),
    "S04": Szenario(s04_http_threads, "Threading / Pooling",
                    "HTTP-Threads am Limit",
                    "currentThreadsBusy = maxThreads, HAProxy-Queue, nach 30 s 503. HTTP-Diagnose fällt mit aus.", [
                        P("parallel", "Parallele Requests", 300, 1, 3000),
                        P("ms", "Laufzeit je Request", 20000, 1, 600000, "ms"),
                        P_dauer(60)]),
    "S05": Szenario(s05_executor, "Threading / Pooling",
                    "Executor BatchHandling (Core 100 / Max 10000)",
                    "poolSize bleibt bei Core, bis die Queue voll ist – dann springen die Threads. Bei MslHandling: Ablehnungen.", [
                        P("executor", "Executor", "BatchHandling", auswahl=EXECUTOREN),
                        P("schritte", "Aufgaben je Schritt", "100,900,100,400", hilfe="kommagetrennt; MslHandling mit 1050 zeigt Ablehnungen"),
                        P("pause", "Pause zwischen Schritten", 3, 0, 120, "s"),
                        P_dauer(60, "Laufzeit je Aufgabe")]),
    "S06": Szenario(s06_timer_tickt_nicht, "Scheduler",
                    "Timer tickt nicht mehr („Cronjob läuft manchmal nicht“)",
                    "Heartbeat: Sekunden seit letztem Lauf steigen linear – ohne Fehler, ohne Log. Misfires erst im Nachhinein.", [
                        P("ursache", "Ursache", "sperre", auswahl=["sperre", "lange-laeufe"],
                          hilfe="sperre = Kundenfall (Abgleich hängt an Tabellensperre), lange-laeufe = Timer-Threads direkt belegt"),
                        P("timer", "Scheduler (nur lange-laeufe)", "ejb", auswahl=["ejb", "quartz"]),
                        P("anzahl", "Lange Läufe (nur lange-laeufe)", 3, 1, 50, hilfe="≥ Pool-Größe (EJB 3, Quartz 5), damit alle Threads belegt sind"),
                        P_dauer(240, "Dauer der Störung"),
                        P("nachlauf", "Nachlauf", 40, 0, 600, "s")]),
    "S07": Szenario(s07_transaktion, "Transaction Timeouts",
                    "Transaktion länger als erlaubt",
                    "Buchungen hängen bis Methodenende, Rollback erst danach; ab 60 s Logeintrag „Transaktion läuft seit …“.", [
                        P("sekunden", "Laufzeit der Transaktion", 90, 5, 3600, "s"),
                        P("timeout", "Transaction Timeout", 30, 0, 14400, "s", "0 = Default des TX-Managers (Kunde 14400 s)"),
                        P("sperre_id", "Gesperrte Baugruppe", 42, 1, 10000),
                        P("buchungen", "Buchende Clients", 5, 0, 200)]),
    "S08": Szenario(s08_sessions, "Session-Pooling",
                    "HTTP-Sessions füllen sich",
                    "tomcat_sessions_activesessions und Heap steigen und bleiben 30 min.", [
                        P("parallel", "Clients", 20, 1, 500),
                        P("kb", "Größe je Session", 50, 1, 10000, "KB"),
                        P_dauer(60)]),
    "S09": Szenario(s09_facade_grenzen, "Sind die Grenzen okay?",
                    "Facade: Heap größer als Container-Limit",
                    "Container-Speicher am Limit, Swap, dann Exit 137 und Neustart – kein OutOfMemoryError.", [
                        P("schritt_mb", "Heap je Schritt", 100, 1, 1000, "MB"),
                        P("schritte", "Höchstens Schritte", 20, 1, 200),
                        P("pause", "Pause zwischen Schritten", 3, 0, 120, "s")],
                    voraussetzung="Facade muss laufen: ./start.sh kunde --facade"),
    "S10": Szenario(s10_file_descriptors, "Sind die Grenzen okay?",
                    "File Descriptors: 440 gut? 500 gut?",
                    "OpenFileDescriptorCount steigt je Schritt, Limit 4096 → mes:fd_auslastung.", [
                        P("clients", "Socket-Clients", 300, 0, 2000),
                        P("schritt", "Dateien je Schritt", 500, 1, 4000),
                        P("schritte", "Schritte", 6, 1, 50),
                        P("nachlauf", "Nachlauf", 30, 0, 600, "s")]),
    "S11": Szenario(s11_intervall, "Scheduler",
                    "Job läuft länger als sein Intervall („von 1/5 auf 10“)",
                    "Ohne Schutz belegt der Job Laufzeit ÷ Intervall Timer-Threads, der Heartbeat bleibt stehen. "
                    "Mit singleton-lock warten fällige Läufe auf die Sperre, nach 30 s SingletonTimeout. Mit ueberspringen: ein Thread.", [
                        P("intervall", "Intervall", 10, 1, 3600, "s"),
                        P("laufzeit", "Laufzeit je Lauf", 35, 1, 3600, "s"),
                        P("schutz", "Überlappungsschutz", "ohne", auswahl=["ohne", "ueberspringen", "singleton-lock"],
                          hilfe="ohne = Läufe überlappen, ueberspringen = Termin entfällt, singleton-lock = @Singleton mit Default-Sperre"),
                        P_dauer(120),
                        P("nachlauf", "Nachlauf", 40, 0, 600, "s")]),
    "S12": Szenario(s12_nachrichten, "Messaging (ActiveMQ / MDB)",
                    "Nachrichten stauen sich in der Queue",
                    "Queue-Tiefe steigt linear, Durchsatz raus < rein, 10 von 10 MDB-Instanzen aktiv, Wartezeit in der Queue wächst. "
                    "Bei gift: Wiederholungen und Dead Letter Queue.", [
                        P("ursache", "Ursache", "langsam", auswahl=["langsam", "sperre", "gift"],
                          hilfe="langsam = Verarbeitung dauert, sperre = MDB bucht in eine gesperrte Tabelle, gift = Nachrichten scheitern immer"),
                        P("rate", "Nachrichten pro Sekunde", 15, 1, 500),
                        P("ms", "Verarbeitungszeit je Nachricht", 1000, 0, 60000, "ms", "nur langsam und gift"),
                        P("gift_prozent", "Anteil Gift", 20, 0, 100, "%", "nur gift"),
                        P_dauer(120),
                        P("nachlauf", "Rückstand abbauen", 60, 0, 1800, "s")]),
    "S13": Szenario(s13_wartung, "Wartung und Kapazität",
                    "Ein Applikationsserver in Wartung (N−1)",
                    "Zwei Cores je rund 55 % – einer geht in Wartung, HAProxy verteilt um, der andere läuft über: "
                    "Bean-Pool 50/50, Wartende, nach 30 s Fehler. Warnstufe bei zwei Servern: jeder unter 50 %.", [
                        P("rate", "Requests pro Sekunde", 110, 1, 2000),
                        P("ms", "Laufzeit je Request", 500, 1, 60000, "ms"),
                        P("server", "Server in Wartung", "core", auswahl=["core", "core2"]),
                        P("vorlauf", "Vorlauf mit zwei Servern", 30, 0, 600, "s"),
                        P_dauer(120, "Dauer der Wartung"),
                        P("nachlauf", "Nach der Freigabe", 30, 0, 600, "s")],
                    voraussetzung="Zweiter Core muss laufen: ./start.sh kunde --core2"),
    "S14": Szenario(s14_speicher, "Sind die Grenzen okay?",
                    "Speicher außerhalb des Heaps (Singleton)",
                    "Heap bleibt niedrig, Threads und Direct Buffer wachsen – die Container-Belegung läuft ans Limit. "
                    "Nur die Container-Sicht zeigt es (cAdvisor, TotalMemorySize/FreeMemorySize).", [
                        P("threads_je_schritt", "Threads je Schritt", 300, 0, 2000),
                        P("stack_kb", "Belegter Stack je Thread", 256, 16, 768, "KB"),
                        P("offheap_mb_je_schritt", "Direct Buffer je Schritt", 100, 0, 1000, "MB"),
                        P("schritte", "Höchstens Schritte", 6, 1, 50),
                        P("ziel_prozent", "Anhalten bei Container-Belegung", 92, 10, 150, "%",
                          "über 100 % beendet der Kernel den Singleton (Exit 137, Neustart)"),
                        P("pause", "Pause zwischen Schritten", 5, 0, 120, "s"),
                        P("halten", "Halten", 60, 0, 1800, "s")]),
    "S15": Szenario(s15_sitzungsgrenze, "DB-Verbindungen",
                    "Grenze der Datenbank: die 150 Verbindungen",
                    "Core und FileProcessing zusammen über der Grenze: sofort ORA-02391 (DbSitzungslimit), obwohl der eigene "
                    "Pool noch Luft hat. Oracle-Sessions je User = Grenze.", [
                        P("grenze", "Welche Grenze", "benutzer", auswahl=["benutzer", "prozesse"],
                          hilfe="benutzer = SESSIONS_PER_USER per Profil, prozesse = echte Prozessgrenze der DB (Oracle Free: 200)"),
                        P("limit", "Sessions für MES_LOCAL", 60, 1, 1000, hilfe="nur grenze = benutzer"),
                        P("parallel", "Langsame Abfragen je Server", 40, 1, 200),
                        P("sekunden", "Laufzeit je Abfrage", 20, 1, 600, "s"),
                        P_dauer(60)]),
    "S16": Szenario(s16_kundenprofil, "Warnstufen / Baseline",
                    "Normalbetrieb mit dem Lastprofil des Kunden",
                    "7 Mio. Requests/Tag ≈ 81/s (43 % Logging), Dateien per TCP – Auslastung im Normalbetrieb und in der Spitze "
                    "als Grundlage für die Warnstufen. Am Ende: Spitzenwerte und Antwortzeiten.", [
                        P("faktor", "Faktor auf das Tagesmittel", 1.0, 0.1, 10.0, hilfe="1 = Mittel 81/s, 3 = angenommene Spitze"),
                        P("log_anteil", "Anteil Logeinträge", 43, 0, 100, "%", "Kunde: 3 von 7 Mio. Requests"),
                        P("dateien", "Dateien per TCP", "ja", auswahl=["ja", "nein"]),
                        P_dauer(300)]),
    "S17": Szenario(s17_logflut, "Logging",
                    "Log-Flut: Logging bremst die Anwendung",
                    "Log-Queue füllt sich, Verzug wächst. unbegrenzt: Heap steigt; verwerfen: Einträge gehen verloren; "
                    "blockieren: HTTP-Threads warten auf die Queue, fachliche Requests werden langsam.", [
                        P("modus", "Queue-Verhalten", "unbegrenzt", auswahl=["unbegrenzt", "verwerfen", "blockieren"],
                          hilfe="unbegrenzt = vermutlich Kundenstand"),
                        P("rate", "Logeinträge pro Sekunde", 400, 1, 5000),
                        P("groesse_kb", "Größe je Eintrag", 8, 1, 512, "KB"),
                        P("schreiblimit", "Schreiber schafft", 100, 0, 100000, "Zeilen/s", "0 = ohne Grenze"),
                        P("kapazitaet", "Queue-Kapazität", 5000, 1, 1000000, hilfe="nur verwerfen und blockieren"),
                        P("fachlich", "Fachliche Requests pro Sekunde", 20, 0, 1000),
                        P_dauer(120),
                        P("nachlauf", "Nachlauf", 60, 0, 1800, "s")]),
    "S18": Szenario(s18_leck, "DB-Verbindungen",
                    "Connection-Leck: Verbindungen kommen nicht zurück",
                    "Active steigt stufenweise ohne Last, Oracle zeigt die Sessions INAKTIV (anders als S02: aktiv), "
                    "älteste Connection wächst. Ist der Pool voll, scheitern Leser nach 30 s mit PoolErschoepft.", [
                        P("datasource", "DataSource", "MES_Connection", auswahl=["MES_Connection", "Master_MES_Connection"]),
                        P("anzahl", "Connections je Schritt", 5, 1, 50),
                        P("intervall", "Abstand der Schritte", 10, 1, 600, "s"),
                        P("lesen", "Lesende Clients", 5, 0, 200),
                        P_dauer(120, "Dauer des Lecks"),
                        P("halten", "Danach beobachten", 60, 0, 3600, "s")]),
    "S19": Szenario(s19_gc, "Sind die Grenzen okay?",
                    "GC-Spirale: Heap fast voll",
                    "Old Gen fast voll, Heap nach GC bleibt oben, GC-Anteil steigt auf zweistellige Prozent, Antwortzeiten "
                    "springen, bei weiterem Wachstum OutOfMemoryError.", [
                        P("leck_mb", "Dauerhaft belegter Heap", 600, 0, 2000, "MB", "Core: -Xmx1024m, Old Gen ≈ 680 MB"),
                        P("schritt_mb", "Leck je Schritt", 100, 1, 500, "MB"),
                        P("muell_rate", "Müll-Requests pro Sekunde", 40, 0, 2000),
                        P("muell_kb", "Müll je Request", 512, 1, 65536, "KB"),
                        P("lese_rate", "Lesezugriffe pro Sekunde", 20, 0, 1000),
                        P("vorlauf", "Vorlauf ohne Leck", 20, 0, 600, "s"),
                        P_dauer(120),
                        P("nachlauf", "Nachlauf", 30, 0, 600, "s")]),
}


def parameter_pruefen(kennung, roh=None):
    """Prüft die Parameter vollständig, bevor etwas gestartet wird. Fehler → ValueError."""
    p = SZENARIEN[kennung].werte(roh)
    if kennung == "S05":
        _zahlenliste(p.schritte, "schritte")
    return p


def szenario_starten(kennung, roh=None):
    """Führt ein Szenario mit den gegebenen Parametern aus (roh: dict name → wert)."""
    sz = SZENARIEN[kennung]
    p = parameter_pruefen(kennung, roh)
    werte = " ".join(f"{k}={v}" for k, v in vars(p).items())
    print(f"=== {kennung}: {sz.titel} ===")
    if werte:
        print(f"    Parameter: {werte}")
    sz.funktion(p)
    print(f"=== {kennung} beendet ===")


# ─── Kommandozeile ─────────────────────────────────────────────────────────

def _paare(liste, option):
    paare = {}
    for eintrag in liste:
        if "=" not in eintrag:
            raise ValueError(f"{option} erwartet name=wert, bekommen: '{eintrag}'")
        name, wert = eintrag.split("=", 1)
        paare[name.strip()] = wert
    return paare


def szenario_liste():
    # nach Kundenthema gruppiert, in der Reihenfolge des ersten Auftretens (wie in der Weboberfläche)
    module = {}
    for k, sz in SZENARIEN.items():
        module.setdefault(sz.modul, []).append((k, sz))
    for modul, eintraege in module.items():
        print(f"\n{modul}")
        for k, sz in eintraege:
            print(f"  {k}  {sz.titel}")
            if sz.parameter:
                print("       " + " ".join(f"{p.name}={p.standard}" for p in sz.parameter))
    print("\nParameter ändern: szenario S01 -p buchen=200 -p dauer=60")


def main():
    global HOST
    p = argparse.ArgumentParser(description="Last und Störungsszenarien für die MES-Demo",
                                formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    p.add_argument("--host", default=HOST, help="Demo-VM (Standard: %(default)s)")
    sub = p.add_subparsers(dest="kommando")
    sub.add_parser("hilfe")
    st = sub.add_parser("status")
    st.add_argument("--rollen", default="core,fileprocessing,singleton")
    st.add_argument("--intervall", type=int, default=5)
    st.add_argument("--sperren", action="store_true", help="zusätzlich Oracle-Blockierungen anzeigen")
    st.add_argument("--haproxy", action="store_true", help="zusätzlich HAProxy-Warteschlange anzeigen")
    sz = sub.add_parser("szenario")
    sz.add_argument("name", help="S01 … S10 oder 'liste'")
    sz.add_argument("--dauer", type=int, help="Kurzform für -p dauer=<s>")
    sz.add_argument("-p", "--param", action="append", default=[],
                    help="name=wert, mehrfach möglich; Namen und Standardwerte: 'szenario liste'")
    la = sub.add_parser("last")
    la.add_argument("--ziel", default="haproxy", choices=list(ROLLEN))
    la.add_argument("--pfad", default="/baugruppe/zufall/buchung")
    la.add_argument("--methode", default="POST")
    la.add_argument("--parallel", type=int, default=20)
    la.add_argument("--dauer", type=int, default=60)
    la.add_argument("--pause", type=float, default=0.0, help="Sekunden zwischen zwei Requests je Thread")
    la.add_argument("--param", action="append", default=[], help="name=wert, mehrfach möglich")
    so = sub.add_parser("sockets")
    so.add_argument("--verbindungen", type=int, default=100)
    so.add_argument("--halten", type=int, default=60)
    so.add_argument("--datei-intervall", type=float, default=0.0, help="0 = Verbindung nur halten")
    sub.add_parser("reset")
    args = p.parse_args()
    HOST = args.host

    try:
        if args.kommando in (None, "hilfe"):
            print(__doc__)
        elif args.kommando == "status":
            while True:
                zeige_status(args.rollen.split(","), mit_sperren=args.sperren, mit_haproxy=args.haproxy)
                time.sleep(args.intervall)
        elif args.kommando == "szenario":
            name = args.name.upper()
            if name == "LISTE" or name not in SZENARIEN:
                szenario_liste()
                return
            try:
                roh = _paare(args.param, "-p")
                if args.dauer:
                    roh["dauer"] = args.dauer
                parameter_pruefen(name, roh)
            except ValueError as e:
                print(f"Fehler: {e}")
                sys.exit(2)
            szenario_starten(name, roh)
        elif args.kommando == "last":
            params = _paare(args.param, "--param")
            last = Last(args.ziel, args.pfad, args.methode.upper(), args.parallel, params, args.pause).start()
            try:
                beobachten(args.dauer, [r for r in ("core", "fileprocessing", "singleton")], [last])
            finally:
                last.stop()
        elif args.kommando == "sockets":
            clients = SocketClients(args.verbindungen, args.datei_intervall).start()
            try:
                beobachten(args.halten, ["fileprocessing"], [clients])
            finally:
                clients.stop()
        elif args.kommando == "reset":
            reset()
    except KeyboardInterrupt:
        print("\nAbgebrochen – räume auf …")
        reset()
        sys.exit(130)


if __name__ == "__main__":
    main()
