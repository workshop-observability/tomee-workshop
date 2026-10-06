#!/usr/bin/env python3
"""
server.py – Weboberfläche für mes_last.py (Laststeuerung).

Liefert die Vue-Oberfläche aus (Verzeichnis static/) und eine kleine REST-API.
Jeder Lauf (Szenario, freie Last, Socket-Clients, Reset) ist ein eigener
mes_last.py-Prozess. Stoppen schickt SIGINT – genau wie Strg+C im Terminal –,
damit die Aufräumlogik der Szenarien unverändert greift.

Nur Python-Standardbibliothek.

  MES_HOST=localhost STEUERUNG_PORT=8070 python3 server.py

API
  GET    /api/info                 Ziel-Host, Ports
  GET    /api/szenarien            Szenarien und freie Kommandos mit Parametern
  GET    /api/status               Live-Ampel (wie 'mes_last.py status --sperren --haproxy')
  GET    /api/laeufe               alle Läufe
  POST   /api/laeufe               {"art": "szenario"|"last"|"sockets"|"reset", "id": "S02", "parameter": {...}}
  GET    /api/laeufe/<n>?ab=<zeile> Ausgabe ab Zeile
  DELETE /api/laeufe/<n>           laufend: stoppen (SIGINT) · beendet: aus der Liste entfernen
"""

import concurrent.futures
import json
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

HIER = os.path.dirname(os.path.abspath(__file__))
# Im Container liegt mes_last.py neben server.py, im Repo eine Ebene höher.
MES_LAST = next(p for p in (os.path.join(HIER, "mes_last.py"), os.path.join(HIER, "..", "mes_last.py"))
                if os.path.exists(p))
sys.path.insert(0, os.path.dirname(MES_LAST))
import mes_last  # noqa: E402  (Parameter-Schema und Live-Status kommen aus demselben Code wie die CLI)
from erklaerungen import ERKLAERUNGEN  # noqa: E402  (ausführliche, zugeklappte Texte je Szenario)

HOST = os.environ.get("MES_HOST", "localhost")
PORT = int(os.environ.get("STEUERUNG_PORT", "8070"))
STATIC = os.environ.get("STEUERUNG_STATIC", os.path.join(HIER, "static"))
MAX_ZEILEN = 20000          # Ausgabe je Lauf, ältere Zeilen werden verworfen
STOPP_FRIST = 45            # Sekunden Aufräumzeit nach SIGINT, danach SIGTERM
mes_last.HOST = HOST

P = mes_last.P
FREIE_KOMMANDOS = {
    "last": {
        "titel": "Freie HTTP-Last",
        "beschreibung": "Feuert Requests mit fester Parallelität gegen einen Applikationsserver oder HAProxy.",
        "parameter": [
            P("ziel", "Ziel", "haproxy", auswahl=list(mes_last.ROLLEN)),
            P("pfad", "Pfad unter /mes/api", "/baugruppe/zufall/buchung"),
            P("methode", "Methode", "POST", auswahl=["GET", "POST", "DELETE"]),
            P("parallel", "Parallele Clients", 20, 1, 3000),
            P("pause", "Pause je Client", 0.0, 0.0, 60.0, "s"),
            P("dauer", "Dauer", 60, 5, 3600, "s"),
            P("param", "Query-Parameter", "", hilfe="name=wert, mehrere mit Komma: sekunden=10,datasource=MES_Connection"),
        ],
    },
    "sockets": {
        "titel": "Socket-Clients (FileProcessing)",
        "beschreibung": "Öffnet TCP-Verbindungen auf die Ports 50000–50004; optional mit Dateiversand.",
        "parameter": [
            P("verbindungen", "Verbindungen", 100, 1, 3000),
            P("halten", "Dauer", 60, 5, 3600, "s"),
            P("datei_intervall", "Dateiintervall je Client", 0.0, 0.0, 60.0, "s", "0 = Verbindung nur halten"),
        ],
    },
    "reset": {
        "titel": "Alle Störungen zurücknehmen",
        "beschreibung": "Sperren, Lecks, blockierte Timer usw. auf allen Applikationsservern beenden.",
        "parameter": [],
    },
}


def _werte(parameter, roh):
    bekannt = {p.name: p for p in parameter}
    unbekannt = set(roh) - set(bekannt)
    if unbekannt:
        raise ValueError(f"unbekannte Parameter: {', '.join(sorted(unbekannt))}")
    return {n: p.wandeln(roh[n]) if n in roh and roh[n] != "" else p.standard for n, p in bekannt.items()}


def kommandozeile(art, kennung, roh):
    """Prüft die Parameter und baut die Argumente für mes_last.py. Fehler → ValueError."""
    roh = {k: v for k, v in (roh or {}).items() if v is not None}
    if art == "szenario":
        if kennung not in mes_last.SZENARIEN:
            raise ValueError(f"unbekanntes Szenario: {kennung}")
        p = vars(mes_last.parameter_pruefen(kennung, roh))
        standard = {x.name: x.standard for x in mes_last.SZENARIEN[kennung].parameter}
        argv = ["szenario", kennung]
        for name, wert in p.items():
            if wert != standard[name]:
                argv += ["-p", f"{name}={wert}"]
        return argv, f"{kennung} {mes_last.SZENARIEN[kennung].titel}"
    if art not in FREIE_KOMMANDOS:
        raise ValueError(f"unbekannte Art: {art}")
    w = _werte(FREIE_KOMMANDOS[art]["parameter"], roh)
    if art == "last":
        argv = ["last", "--ziel", w["ziel"], "--pfad", "/" + w["pfad"].lstrip("/"), "--methode", w["methode"],
                "--parallel", str(w["parallel"]), "--pause", str(w["pause"]), "--dauer", str(w["dauer"])]
        for paar in filter(None, (x.strip() for x in w["param"].split(","))):
            if "=" not in paar:
                raise ValueError(f"Query-Parameter: name=wert erwartet, bekommen '{paar}'")
            argv += ["--param", paar]
        return argv, f"Last {w['methode']} {w['ziel']} {w['pfad']} ×{w['parallel']}"
    if art == "sockets":
        return (["sockets", "--verbindungen", str(w["verbindungen"]), "--halten", str(w["halten"]),
                 "--datei-intervall", str(w["datei_intervall"])], f"Sockets ×{w['verbindungen']}")
    return ["reset"], "Reset"


# ─── Läufe ─────────────────────────────────────────────────────────────────

class Lauf:
    def __init__(self, nummer, art, kennung, titel, argv, parameter):
        self.nummer, self.art, self.kennung, self.titel = nummer, art, kennung, titel
        self.argv, self.parameter = argv, parameter
        self.zeilen, self.verworfen = [], 0
        self.beginn, self.ende, self.rueckgabe = time.time(), None, None
        self.stopp_angefordert = False
        self._lock = threading.Lock()
        self.prozess = subprocess.Popen(
            [sys.executable, "-u", MES_LAST, "--host", HOST] + argv,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        threading.Thread(target=self._lesen, daemon=True).start()

    def _lesen(self):
        for zeile in self.prozess.stdout:
            with self._lock:
                self.zeilen.append(zeile.rstrip("\n"))
                if len(self.zeilen) > MAX_ZEILEN:
                    ueberzahl = len(self.zeilen) - MAX_ZEILEN
                    del self.zeilen[:ueberzahl]
                    self.verworfen += ueberzahl
        self.rueckgabe = self.prozess.wait()
        self.ende = time.time()

    @property
    def laeuft(self):
        return self.ende is None

    def stoppen(self):
        if not self.laeuft or self.stopp_angefordert:
            return
        self.stopp_angefordert = True
        self.prozess.send_signal(signal.SIGINT)

        def notbremse():
            try:
                self.prozess.wait(STOPP_FRIST)
            except subprocess.TimeoutExpired:
                self.prozess.terminate()
                try:
                    self.prozess.wait(5)
                except subprocess.TimeoutExpired:
                    self.prozess.kill()
        threading.Thread(target=notbremse, daemon=True).start()

    def ausgabe(self, ab):
        with self._lock:
            start = max(ab - self.verworfen, 0)
            return self.zeilen[start:], self.verworfen + len(self.zeilen)

    def als_dict(self):
        zustand = "läuft" if self.laeuft else ("gestoppt" if self.stopp_angefordert else
                                                ("beendet" if self.rueckgabe == 0 else "Fehler"))
        if self.laeuft and self.stopp_angefordert:
            zustand = "räumt auf"
        return {"nummer": self.nummer, "art": self.art, "id": self.kennung, "titel": self.titel,
                "parameter": self.parameter, "kommando": "python3 lasttest/mes_last.py --host <vm> " + " ".join(self.argv),
                "beginn": self.beginn, "ende": self.ende, "rueckgabe": self.rueckgabe, "zustand": zustand,
                "laeuft": self.laeuft}


LAEUFE = {}
LAEUFE_LOCK = threading.Lock()
_zaehler = iter(range(1, 10 ** 9))


def lauf_starten(daten):
    art = daten.get("art", "szenario")
    kennung = (daten.get("id") or "").upper() or None
    roh = daten.get("parameter") or {}
    argv, titel = kommandozeile(art, kennung, roh)
    with LAEUFE_LOCK:
        lauf = Lauf(next(_zaehler), art, kennung, titel, argv, roh)
        LAEUFE[lauf.nummer] = lauf
    return lauf


def alle_stoppen(*_):
    laufend = [l for l in LAEUFE.values() if l.laeuft]
    print(f"Beende – stoppe {len(laufend)} laufende(n) Lauf/Läufe mit SIGINT …", flush=True)
    for l in laufend:
        l.stoppen()
    for l in laufend:
        try:
            l.prozess.wait(STOPP_FRIST)
        except subprocess.TimeoutExpired:
            l.prozess.kill()
        print(f"  #{l.nummer} {l.titel}: Rückgabe {l.prozess.returncode}", flush=True)
    os._exit(0)


# ─── Live-Status ───────────────────────────────────────────────────────────

_pool = concurrent.futures.ThreadPoolExecutor(max_workers=8)


def live_status(rollen):
    zukuenfte = {r: _pool.submit(mes_last.ampel, r) for r in rollen}
    oracle = _pool.submit(mes_last.sperren_zeile)
    haproxy = _pool.submit(mes_last.haproxy_zeile)
    return {"zeit": time.strftime("%H:%M:%S"),
            "rollen": [{"rolle": r, "text": f.result().strip(),
                        "erreichbar": "nicht erreichbar" not in f.result()} for r, f in zukuenfte.items()],
            "oracle": oracle.result(), "haproxy": haproxy.result()}


# ─── HTTP ──────────────────────────────────────────────────────────────────

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=STATIC, **kwargs)

    def log_message(self, fmt, *args):
        if not self.path.startswith("/api/laeufe/") and not self.path.startswith("/api/status"):
            sys.stderr.write("%s %s\n" % (self.address_string(), fmt % args))

    def _json(self, daten, status=200):
        roh = json.dumps(daten, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(roh)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(roh)

    def _lauf(self, url):
        try:
            return LAEUFE.get(int(url.path.rsplit("/", 1)[-1]))
        except ValueError:
            return None

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/api/info":
            return self._json({"host": HOST, "rollen": mes_last.ROLLEN, "socketPorts": list(mes_last.SOCKET_PORTS)})
        if url.path == "/api/szenarien":
            return self._json({
                "szenarien": [dict(sz.als_dict(k), erklaerung=ERKLAERUNGEN.get(k))
                              for k, sz in mes_last.SZENARIEN.items()],
                "kommandos": [{"art": k, "titel": v["titel"], "beschreibung": v["beschreibung"],
                               "parameter": [p.als_dict() for p in v["parameter"]]}
                              for k, v in FREIE_KOMMANDOS.items()]})
        if url.path == "/api/status":
            rollen = parse_qs(url.query).get("rollen", ["core,fileprocessing,singleton"])[0].split(",")
            rollen = [r for r in rollen if r in mes_last.ROLLEN and r != "haproxy"]
            return self._json(live_status(rollen))
        if url.path == "/api/laeufe":
            return self._json([l.als_dict() for l in sorted(LAEUFE.values(), key=lambda l: -l.nummer)])
        if url.path.startswith("/api/laeufe/"):
            lauf = self._lauf(url)
            if not lauf:
                return self._json({"fehler": "Lauf nicht gefunden"}, 404)
            ab = int(parse_qs(url.query).get("ab", ["0"])[0] or 0)
            zeilen, naechste = lauf.ausgabe(ab)
            return self._json({"lauf": lauf.als_dict(), "zeilen": zeilen, "naechste": naechste})
        if url.path.startswith("/api/"):
            return self._json({"fehler": "unbekannter Pfad"}, 404)
        # Single-Page-App: unbekannte Pfade liefern index.html
        if not os.path.exists(os.path.join(STATIC, url.path.lstrip("/"))) or url.path == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        url = urlparse(self.path)
        if url.path != "/api/laeufe":
            return self._json({"fehler": "unbekannter Pfad"}, 404)
        try:
            laenge = int(self.headers.get("Content-Length") or 0)
            daten = json.loads(self.rfile.read(laenge) or b"{}")
            lauf = lauf_starten(daten)
        except (ValueError, json.JSONDecodeError) as e:
            return self._json({"fehler": str(e)}, 400)
        return self._json(lauf.als_dict(), 201)

    def do_DELETE(self):
        url = urlparse(self.path)
        lauf = self._lauf(url) if url.path.startswith("/api/laeufe/") else None
        if not lauf:
            return self._json({"fehler": "Lauf nicht gefunden"}, 404)
        if lauf.laeuft:
            lauf.stoppen()
            return self._json(lauf.als_dict())
        with LAEUFE_LOCK:
            LAEUFE.pop(lauf.nummer, None)
        return self._json({"entfernt": lauf.nummer})


def main():
    # Ein als Hintergrundjob gestarteter Prozess erbt "SIGINT ignorieren" – das würde an die
    # mes_last.py-Prozesse weitergegeben, und Stoppen (Strg+C) käme nie an.
    signal.signal(signal.SIGINT, signal.default_int_handler)
    signal.signal(signal.SIGTERM, alle_stoppen)
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    server.daemon_threads = True
    print(f"Laststeuerung auf http://0.0.0.0:{PORT} – Ziel {HOST}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        alle_stoppen()


if __name__ == "__main__":
    main()
