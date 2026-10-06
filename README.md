# MES-Demo-Umgebung

Lauffähige Nachbildung des Zollner-MES-Aufbaus für den Workshop
„Monitorability & Performance Tuning". Hier lassen sich die Störungsbilder des
Kunden gezielt erzeugen und über JMX, Prometheus und Grafana beobachten.

- **Szenarien, Ablauf und Lehrpunkte:** [workshop/Demo-Szenarien.md](../workshop/Demo-Szenarien.md)
- **Alle exportierten Metriken:** [analyse/JMX-Exporter-Metriken.md](../analyse/JMX-Exporter-Metriken.md)

> Die Demo ist eine **vereinfachte Nachbildung**, kein Abbild der Produktion.
> Aussagen über das Kundensystem müssen aus `resosurcen-vom-kunden/` belegt sein.

---

## 1. Aufbau

```
                     ┌──────────── HAProxy 3.2 ────────────┐
   Browser/Lasttest →│ :8090 HTTP   :8095   :50000-50004 TCP│  Statistik + /metrics :8989
                     └───┬──────────────┬────────────┬──────┘
                         │              │            │
            ┌────────────▼──┐  ┌────────▼────┐  ┌────▼───────────┐   ┌─────────────┐
            │ core          │  │ singleton   │  │ fileprocessing │   │ facade      │ (Profil
            │ :8200 JMX 9200│  │ :8100  9100 │  │ :8300  9300    │   │ :8400 9300→ │  "facade")
            └──────┬────────┘  └──────┬──────┘  └──────┬─────────┘   └─────────────┘
                   │  TomEE Plume 10.1.2 auf Rocky Linux 9, Java 21, JMX Exporter :8888
                   ▼                  ▼                ▼
            ┌───────────────────────────────┐
            │ Oracle Free 23 (FREEPDB1)     │
            │ MES_LOCAL, MES_MASTER, ...    │
            └───────────────────────────────┘

   Prometheus :9090 ← alle Exporter, HAProxy, cAdvisor     Grafana :3000 (Übersicht + 1 je Szenario)
   Laststeuerung :8070 (Szenarien S01–S10 im Browser)

   Portal :8080 → /frontend/ /grafana/ /prometheus/ /haproxy /cadvisor/
                  /core/ /fileprocessing/ /singleton/ /facade/ /lb/ /metriken/…
                  (ein Eingang für alles; die Einzelports bleiben zusätzlich offen)
```

| Container | Rolle | Besonderheit |
|---|---|---|
| `mes-core` | HTTP-Anfragen (Baugruppen buchen/lesen) | Kunden-JMX-Port 9200 |
| `mes-fileprocessing` | TCP-Socket-Server 50000–50004, Dateiverarbeitung | FD-Limit 4096, eigener Bean-Container |
| `mes-singleton` | Stammdatenabgleich, Oracle-Sperrüberwachung | Heap/Limit-Verhältnis wie beim Kunden (knapp) |
| `mes-facade` | nur mit `--facade` | **beide** Kundenfehler: `-Xmx` > Container-Limit, JMX-Port 9300 statt 9400 |
| `mes-oracle` | Oracle Free 23, Schema aus `oracle/init/` | Daten nur im Container: `./start.sh --reset` setzt zurück |
| `mes-haproxy` | Ports wie im Architekturbild des Kunden | `maxconn 200` je Server (Annahme) |
| `mes-prometheus`, `mes-grafana`, `mes-cadvisor` | Monitoring | Regeln mit Startwerten in `prometheus/regeln.yml` |
| `mes-laststeuerung` | Weboberfläche für die Szenarien (`:8070`) | Host-Netz, startet `mes_last.py`-Prozesse |
| `mes-portal` | ein Eingang für alle Oberflächen (`:8080`) | nginx, verteilt nach Pfad – `portal/nginx.conf` |

Alle TomEE-Container nutzen **dasselbe Image** und dieselbe Anwendung (`mes-demo-app`).
Die Umgebungsvariable `MES_ROLLE` entscheidet nur über Hintergrunddienste.

---

## 2. Starten und Stoppen

Voraussetzungen: Linux-Server (Rocky/Alma/RHEL, Fedora, Ubuntu oder Debian) mit
sudo-Rechten, ca. **8 GB freier RAM**, 4+ Kerne, Internetzugang beim ersten Build
(Docker-Repository, Maven Central, Docker Hub, ghcr.io).

Das Verzeichnis `code-demo/` auf den Server kopieren (ohne `mes-demo-app/target/`), dann:

```bash
cd code-demo
./start.sh                  # Einstellungen aus .env (beim ersten Mal: Kundenkonfiguration)
./start.sh optimiert        # Tuning-Variante (nur TomEE-Container werden neu erstellt)
./start.sh kunde            # zurück zur Kundenkonfiguration
./start.sh kunde --facade   # zusätzlich Facade-Container
./start.sh --reset          # Oracle-Daten und Metriken verwerfen, frisch starten

docker compose --profile facade stop    # stoppen (startet nach einem Reboot wieder)
./loeschen.sh                           # alles entfernen, nächster Start komplett frisch
```

`start.sh` ist das einzige Skript. Es ruft sich bei Bedarf selbst mit `sudo` auf
und stellt bei jedem Aufruf sicher, dass

1. Docker mit Compose und Buildx installiert ist und läuft; der aufrufende
   Benutzer kommt in die Gruppe `docker` (wirksam ab der nächsten Anmeldung),
2. die Demo-Ports in firewalld bzw. ufw freigegeben sind,
3. der systemd-Dienst `mes-demo` die Demo nach einem Reboot mit denselben
   Einstellungen startet,
4. `.env` existiert (aus `.env.example`). Variante und Facade werden dort
   gespeichert (`KONFIG`, `COMPOSE_PROFILES`).

Danach baut es die Images und wartet, bis alle Applikationsserver antworten.
Der erste Build dauert einige Minuten, danach wenige Sekunden.

`loeschen.sh` nimmt das nach einer Rückfrage wieder zurück: Container, Volumes
(Oracle-Daten, Metriken, Logs), die eigenen Images, den Dienst `mes-demo` und die
Firewall-Freigaben. `.env` wird zu `.env.bak`; der nächste `./start.sh` beginnt
mit den Werten aus `.env.example`. Docker bleibt installiert.

> JMX (9100/9200/9300) läuft ohne Authentifizierung und ist nach dem Start von
> außen erreichbar. Am besten im internen Netz betreiben; steht die Demo für den
> Kunden im Internet (siehe Cloud-Abschnitt unten), gehören dort nur erfundene
> Daten hinein, und die VM wird nach dem Workshop abgeschaltet.

### Gleiche Einstellungen auf jedem Server

Alles, was eingerichtet sein muss, liegt als Datei im Verzeichnis:

| Was | Woher |
|---|---|
| JMX Exporter in jedem TomEE-Container | `tomee/jmx-exporter.yaml` (ins Image gebaut) |
| Prometheus-Ziele und Alarmregeln | `prometheus/prometheus.yml`, `prometheus/regeln.yml` |
| Grafana-Datenquelle, Übersicht „MES – JMX Exporter“ und je Szenario ein Dashboard | `grafana/provisioning/`, `grafana/dashboards/` |
| Heap, Limits, Pools, Variante, Facade | `.env` |

`REMOTE_HOST` bleibt in `.env` leer. `start.sh` ermittelt die Adresse dann bei
jedem Start und schreibt sie nicht zurück. Die `.env` kann deshalb mit umziehen.

**Demo in einer Cloud (Azure, AWS, GCP).** Dort hat die VM nur die private Adresse
ihres virtuellen Netzes (z. B. `172.16.0.4`); die öffentliche Adresse hängt per NAT
davor. Steht sie im Metadatendienst der Cloud (`169.254.169.254`), nimmt `start.sh`
sie von selbst. Hängt sie an einem Load Balancer statt an der Netzwerkkarte, kennt
die VM sie nicht — dann einmal die Adresse nennen, unter der auch SSH läuft:

```bash
./start.sh --host 20.224.241.62
```

Der Wert landet in `.env` und gilt auch nach einem Reboot. Er steuert nur, was in
URLs steht und was als `-Djava.rmi.server.hostname` in die Container geht (JConsole);
die Anwendung selbst lauscht ohnehin auf allen Adressen.

Zusätzlich müssen die Ports in der Firewall der Cloud offen sein (Azure:
Netzwerksicherheitsgruppe von VM oder Subnetz). Das erledigt `start.sh` nicht,
es gibt nur die Firewall des Servers selbst (firewalld/ufw) frei. Liegt ein Load
Balancer davor, müssen die Ports dort zusätzlich als Lastverteilungsregeln
eingetragen sein.

JMX (9100/9200/9300/9400) und Oracle (1521) stehen damit ohne Anmeldung im Netz: nur
erfundene Daten einspielen, die VM nach dem Workshop abschalten oder löschen.

**Wenn die Firewall der Cloud nicht änderbar ist** (fremdes Azure-Konto, nur SSH kommt
durch): Welche Ports durchkommen, misst man vom eigenen Rechner aus, ohne auf der VM
etwas zu starten — ein Ping hilft nicht, der prüft ICMP und nicht den einzelnen Port:

```bash
nmap -Pn -p 80,443,3000,8070,8080,9090 20.224.241.62
```

`-Pn` ist nötig, weil Azure ICMP verwirft und nmap den Host sonst für tot hält.
`open` heißt offen, `closed` heißt „Firewall lässt durch, es hört nur niemand" (also
ebenfalls brauchbar), `filtered` heißt zu. Ohne nmap geht es auch mit netcat, dann
aber ein Port je Durchlauf: `for p in 80 443 3000 8070; do nc -zvw3 <adresse> $p; done`

Kommt nichts durch, bleibt der SSH-Tunnel:

```bash
./zugang.sh tunnel                # fertiger ssh -L …-Befehl über alle Demo-Ports
```

Er macht die Demo auf dem eigenen Rechner unter `localhost` verfügbar, auch JConsole
(dazu `./start.sh --host 127.0.0.1`, damit RMI die richtige Adresse zurückmeldet) und
Oracle. Teilnehmer ohne SSH-Zugang erreicht man so allerdings nicht.

| Dienst | über das Portal `:8080` | eigener Port | Login |
|---|---|---|---|
| Übersichtsseite mit allen Links | `/` | – | – |
| Laststeuerung (Szenarien starten) | `/frontend/` | `:8070` | – |
| Grafana | `/grafana/` | `:3000` (leitet auf `/grafana/` weiter) | admin / admin |
| Prometheus (Alarme: `/alerts`) | `/prometheus/` | `:9090` | – |
| HAProxy-Statistik | `/haproxy` | `:8989` | – |
| cAdvisor | `/cadvisor/` | `:8085/cadvisor/` | – |
| Core / FileProcessing / Singleton | `/core/mes/api/status`, `/fileprocessing/…`, `/singleton/…` | `:8200` / `:8300` / `:8100` + `/mes/api/status` | – |
| über HAProxy | `/lb/mes/api/…`, `/lb/mes/fileprocessing/api/…`, `/lb-idoc/mes/api/…` | `:8090`, `:8095` | – |
| JMX Exporter | `/metriken/core/metrics`, `…/fileprocessing/…`, `…/singleton/…` | `:8882` (core), `8883` (fp), `8881` (singleton), `8884` (facade) | – |
| JConsole / VisualVM | kein HTTP – nicht über 8080 | `jconsole <host>:9200` (core), `9300` (fp), `9100` (singleton) | – |
| Oracle (SQL Developer, DBeaver) | kein HTTP – nicht über 8080 | `<host>:1521/FREEPDB1`, User `MES_MONITOR` | mes_demo |

**Das Portal** (Container `mes-portal`, nginx) ist nur ein zusätzlicher Weg: jeder
Dienst bleibt unter seinem eigenen Port erreichbar, die Szenarien und alle
Anleitungen funktionieren unverändert. Nützlich ist es, wenn in einem fremden
Netz nur ein einziger Port freigegeben werden kann – dann genügt `8080` für alle
Weboberflächen. Der Port lässt sich in `.env` über `PORTAL_PORT` ändern.

Wer einen Dienst ergänzt, trägt ihn in `portal/nginx.conf` und auf der
Übersichtsseite `portal/index.html` ein. Drei Arten der Anbindung, je nachdem,
was der Dienst mit Pfaden macht:

| Art | Wie | Wer |
|---|---|---|
| Präfix abschneiden | `proxy_pass http://ziel:port/;` (mit `/` am Ende) | Applikationsserver, Laststeuerung, Prometheus |
| Präfix durchreichen | `proxy_pass http://ziel:port;` (ohne `/`) – der Dienst muss selbst unter dem Unterpfad ausliefern | Grafana (`GF_SERVER_SERVE_FROM_SUB_PATH`), cAdvisor (`--url_base_prefix`), HAProxy (zweiter Listener `:8990` mit `stats uri /haproxy`) |
| Name erst zur Laufzeit auflösen | `resolver 127.0.0.11` + Variable im `proxy_pass` | Facade – der Container läuft meist gar nicht, sonst startet nginx nicht |

**Hinter einem weiteren Reverse Proxy** (`https://<host>/<pfad>/` → `:8080/`, der Proxy
schneidet `<pfad>` ab): `PORTAL_PFAD=/<pfad>` in `.env` setzen und die Container neu
anlegen (`./start.sh` bzw. `docker compose up -d`). Ohne die Einstellung verlieren
Weiterleitungen und die Dienste mit absoluten Pfaden (Grafana, cAdvisor,
HAProxy-Statistik, ActiveMQ-Konsole) den Unterpfad, und der äußere Proxy antwortet
mit 404. `portal/nginx.conf` ist dafür eine Vorlage, in die der nginx-Container
`${PORTAL_PFAD}` beim Start einsetzt.

Prometheus braucht dafür keine Einstellung: seine Oberfläche ermittelt das Präfix
aus der Adresse im Browser. Grafana dagegen liefert fest unter `/grafana/` aus;
der Aufruf von `:3000` leitet deshalb dorthin weiter.

---

## 3. Die beiden Konfigurationsvarianten

| Datei | `konfig/kunde/` | `konfig/optimiert/` |
|---|---|---|
| `tomee.xml` | Kundendatei; nur `jdbcUrl`, `userName`, `password` geändert (markiert mit `DEMO-ÄNDERUNG`) | jede Abweichung mit `TUNING` und Kundenwert kommentiert |
| `server.xml` | identisch mit `resosurcen-vom-kunden/server.xml` | Executor aktiv, Grenzen gesetzt, Access-Log unter `logs/` |

Beide Dateien werden per Volume nach `conf/` gemountet. Umschalten mit
`./start.sh optimiert` bzw. `./start.sh kunde`.

Weitere Stellschrauben in `.env`: `TIMER_POOL_SIZE` (EJB-Timer-Threads, leer = 3),
`QUARTZ_THREADS`, `SOCKET_TIMEOUT_MS`, `TX_WARN_SEKUNDEN`, `TOMEE_CPUS`,
Heap- und Speicherlimits je Container, `JAVA_OPTS_EXTRA`.

---

## 4. Last und Szenarien

### Weboberfläche (`http://<host>:8070`, auch `http://<host>:8080/frontend/`)

Container `mes-laststeuerung`, startet mit `./start.sh` wie alle anderen Dienste.

- Szenario links wählen, Parameter im Formular ändern (Standardwerte, Grenzen und
  Einheit stehen am Feld; die zuletzt benutzten Werte merkt sich der Browser).
- **Starten** legt einen Lauf an; die Ausgabe erscheint wie im Terminal.
  **Stoppen** entspricht Strg+C – das Szenario räumt auf (Sperren frei, Lecks zu, `reset`).
- Mehrere Läufe gleichzeitig sind möglich, z. B. freie Last plus Szenario.
- Unter jedem Formular steht das gleichwertige Kommando für die Kommandozeile.
- „Auflösung" (zugeklappt): was im Szenario passiert, warum und wie man es verhindert –
  Texte in `lasttest/erklaerungen.py`.
- „Freie Kommandos": beliebige HTTP-Last, Socket-Clients, Reset.
- Live-Status: dieselbe Ampel wie `mes_last.py status --sperren --haproxy`.

Keine Anmeldung – nur im Schulungsnetz betreiben, wie die übrigen Demo-Ports.

### Kommandozeile

```bash
python3 lasttest/mes_last.py --host <host> szenario liste                  # mit Parametern und Standardwerten
python3 lasttest/mes_last.py --host <host> szenario S01                    # geführt, mit Live-Ampel
python3 lasttest/mes_last.py --host <host> szenario S01 -p buchen=300 -p dauer=60
python3 lasttest/mes_last.py --host <host> status --sperren   # nur beobachten
python3 lasttest/mes_last.py --host <host> reset              # Störungen zurücknehmen
```

Nur Python-Standardbibliothek (ab 3.9). Strg+C bricht ab und räumt auf.
Die 10 Szenarien (zugeschnitten auf die Anforderungen des Kunden) und ihr Einsatz im Workshop: [Demo-Szenarien.md](../workshop/Demo-Szenarien.md),
Ursachen und Stellschrauben je Szenario: [Lastszenarien-Ursachen-und-Tuning.md](../workshop/Lastszenarien-Ursachen-und-Tuning.md).

Parameter und Standardwerte stehen je Szenario in `SZENARIEN` in `mes_last.py`.
Weboberfläche und Kommandozeile lesen dieselbe Definition.

---

## 5. Schnittstellen der Anwendung (`/mes/api`)

**Fachlich**

| Methode | Pfad | Wirkung |
|---|---|---|
| GET | `/status` | Rolle und Konfigurationsvariante |
| GET | `/baugruppe/{id}`, `/baugruppe/zufall` | Lesen (wartet in Oracle nie auf Sperren) |
| POST | `/baugruppe/{id}/buchung`, `/baugruppe/zufall/buchung` | `SELECT … FOR UPDATE` + Update + Insert. `?warten=5` → `FOR UPDATE WAIT 5`, `?abfrageTimeout=5` → `setQueryTimeout` |
| POST | `/stammdaten/abgleich`, `/stammdaten/schreiben` | Master lesen / lokal schreiben bzw. Master schreiben |

**Störungen** (`/szenario/…`)

| Pfad | Parameter | Wirkung |
|---|---|---|
| POST/GET/DELETE `db/sperre` | `tabelle` (BAUGRUPPE, BUCHUNG, STAMMDATEN), `modus` (tabelle, zeilen), `von`, `bis`, `sekunden` | fremde Session (MES_REPL, „Replikation") sperrt (S01, S06) |
| GET `db/langsam` | `sekunden`, `datasource` | `DBMS_SESSION.SLEEP` – Connection belegt ohne Sperre (S02) |
| GET `tx/lang` | `sekunden`, `timeout` (0 = Default), `sperreId` | Bean-Managed Transaction (S07) |
| GET `bean/langsam` | `ms` | belegt eine Bean aus dem Default Stateless Container (S03) |
| GET `http/langsam` | `ms` | hält einen HTTP-Thread (S04) |
| GET `executor`, POST `executor/{name}` | `aufgaben`, `ms` | Aufgaben in einen Executor aus `tomee.xml` (S05) |
| GET `scheduler`, POST `scheduler/blockieren` | `art` (ejb, quartz), `anzahl`, `sekunden` | Timer-Threads belegen (S06) |
| GET `session/anlegen` | `kb` | neue HTTP-Session je Aufruf (S08) |
| POST/DELETE `jvm/leck` | `mb` | Heap-Leck (S09, Facade) |
| POST/DELETE `jvm/dateien` | `anzahl` | offene Dateien (S10) |
| DELETE `alle` | – | Sperren, Heap-Leck, Dateien zurücknehmen |

**Diagnose** (`/diagnose/…`)

| Pfad | Inhalt |
|---|---|
| `uebersicht` | Ampel über alle Ebenen (liest dieselben MBeans wie JConsole) |
| `db-sperren` | Blockierketten aus `V$SESSION`, gesperrte Objekte |
| `threads?gruppe=…` | Threads nach Zustand und Namensgruppe, Stacks für eine Gruppe |
| `mbeans?muster=…&attribute=true` | MBean-Inventur, z. B. `muster=openejb.management:*` |
| `konfig` | **effektive** Werte: JVM-Argumente, Container-Limit, Pool-Werte, TX-Timeout |

Achtung: Die Diagnose läuft über denselben HTTP-Connector. Ist er gesättigt,
antwortet auch sie nicht – JMX (JConsole) funktioniert dann weiter.

---

## 6. Verzeichnisse

| Pfad | Inhalt |
|---|---|
| `mes-demo-app/` | Jakarta-EE-10-WAR (Kontext `/mes`). Pakete: `core` (Fachlogik), `szenario` (Störungen), `scheduler`, `fileprocessing`, `monitoring` (eigene MBeans), `rest` |
| `tomee/` | Dockerfile, `setenv.sh`, JMX-Exporter-Regeln, Konfigurationsvarianten |
| `oracle/init/` | Schema und Testdaten (10.000 Baugruppen, 2.000 Stammdaten) |
| `haproxy/`, `prometheus/` | Konfiguration, Alarmregeln (Startwerte) |
| `portal/` | `nginx.conf` (Routen des Eingangs `:8080`), `index.html` (Übersichtsseite) |
| `grafana/` | `dashboards_erzeugen.py` erzeugt `dashboards/mes-jmx.json` (eine Zeile je Metrikgruppe des JMX Exporters) und `dashboards/s01-…json` bis `s10-…json` (je Szenario die entscheidenden Werte; Titel und Beschreibung aus `SZENARIEN` in `mes_last.py`) |
| `lasttest/` | `mes_last.py` (Last, Szenarien, Parameter-Schema), `erklaerungen.py` (Auflösungstexte je Szenario) |
| `lasttest/steuerung/` | Laststeuerung: `server.py` (REST-API, startet `mes_last.py`-Prozesse), `frontend/` (Vue 3 + Vite), `Dockerfile` |

**Eigene MBeans** (Domain `mes.demo`): `JdbcZugriff`, `SchedulerJob`, `Executor`,
`OracleSperren`, `OracleSitzungen`, `Transaktionen`, `Fehler`, `Szenario`,
`SocketServer`.

---

## 7. Entwickeln

```bash
# Anwendung ändern → Image neu bauen (das WAR wird beim Build ins Image kopiert)
docker compose up -d --build core fileprocessing singleton

# nur kompilieren (ohne lokales Maven/Java 21)
docker run --rm -v "$PWD/mes-demo-app":/app:z -v mes-demo-m2:/root/.m2 -w /app \
  maven:3.9-eclipse-temurin-21 mvn -q -B package      # target/ gehört danach root

# Exporter-Regeln geändert → ebenfalls neu bauen (Datei liegt im Image)
# Prometheus-Regeln geändert:
curl -X POST http://localhost:9090/-/reload

# Portal geändert (portal/nginx.conf, portal/index.html – beide sind gemountet):
docker compose restart portal          # nginx.conf; index.html wirkt sofort

# Dashboards geändert (auch nach neuen Szenarien in mes_last.py):
python3 grafana/dashboards_erzeugen.py     # Grafana lädt nach ≤ 30 s neu

# mes_last.py oder Laststeuerung geändert:
docker compose up -d --build laststeuerung

# Oberfläche entwickeln (Hot Reload auf :5173, API vom lokalen server.py):
python3 lasttest/steuerung/server.py &                      # :8070, Ziel MES_HOST (Standard localhost)
cd lasttest/steuerung/frontend && npm install && npm run dev
```

Es gibt keine automatisierten Tests. Geprüft wird am laufenden Stack über die
Szenarien in `lasttest/mes_last.py`.

---

## 8. Stolperfallen

| Symptom | Ursache / Abhilfe |
|---|---|
| JConsole verbindet nicht | `REMOTE_HOST` leer lassen (automatisch) oder auf die von außen erreichbare Adresse setzen (NAT, Hostname); danach `./start.sh` |
| In der Cloud zeigt die Ausgabe `172.16.x.x` | Das ist die private Adresse des virtuellen Netzes. `./start.sh --host <öffentliche Adresse>` – dieselbe, über die auch SSH läuft |
| Cloud: Adresse stimmt, Seiten laden trotzdem nicht | Ports in der Firewall der Cloud (Azure: Netzwerksicherheitsgruppe) nicht frei – dort freigeben oder `./zugang.sh tunnel` nutzen. Liegt ein Load Balancer davor, braucht auch der Regeln für die Ports |
| `permission denied … docker.sock` | Gruppe `docker` gilt erst nach neuer Anmeldung; bis dahin `sudo docker …` |
| Autostart prüfen | `systemctl status mes-demo`, Log: `journalctl -u mes-demo` |
| cAdvisor zeigt keine Container | Docker ≥ 29 mit containerd-Image-Store braucht cAdvisor ≥ 0.60 (`ghcr.io/google/cadvisor`) |
| Prometheus: Label `exported_job` | eigene Labels dürfen nicht `job` oder `instance` heißen (daher `aufgabe`) |
| Facade nach S09 in Neustart-Schleife | gewollt (`restart: on-failure`); `docker compose stop facade` |
| Laststeuerung: Lauf steht auf „räumt auf" | Aufräumen erreicht die TomEE-Container nicht; nach 45 s wird der Prozess beendet. Danach `reset` starten |
| Laststeuerung: S09 ohne Container-Zustand | der Container hat bewusst keinen Docker-Zugriff; `docker inspect mes-facade` auf der VM |
| Portal startet nicht (`host not found in upstream`) | ein Zielcontainer fehlt; `docker compose up -d` und danach `docker compose up -d portal` |
| `:8085` (cAdvisor) zeigt 404 | cAdvisor liegt wegen des Portals unter `/cadvisor/`: `http://<host>:8085/cadvisor/` |
| `:3000` landet auf `:8080/grafana/` | gewollt – Grafana liefert unter dem Unterpfad aus und leitet dorthin weiter. Landet die Weiterleitung auf `localhost:8080`, wurde Grafana ohne bekannte Adresse gestartet (`docker compose up` statt `./start.sh`): `./start.sh` setzt `GF_SERVER_DOMAIN` aus `REMOTE_HOST` |
| Oracle startet langsam | erster Start eines neuen Containers ca. 30–60 s |
