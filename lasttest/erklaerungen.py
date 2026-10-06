"""
erklaerungen.py – ausführliche Erklärung je Szenario (S01–S10) für die Laststeuerung.

Die Oberfläche zeigt die Texte zugeklappt („Auflösung"), damit sie im Workshop
nicht vorwegnehmen, was die Teilnehmer selbst herausfinden sollen.

Je Szenario drei Abschnitte:
  passiert    – was im System geschieht, in der Reihenfolge, in der man es sieht
  warum       – der Mechanismus dahinter
  verhindern  – was hilft (und was nicht); Konfiguration mit Kundenwert → Startwert

Format: Absätze durch Leerzeile getrennt, `Code` in Backticks, Aufzählung mit „- ".
Ausführlich mit Belegen: workshop/Lastszenarien-Ursachen-und-Tuning.md
"""

ERKLAERUNGEN = {
    "S01": {
        "passiert": """Viele Clients buchen parallel. Nach dem Vorlauf sperrt der Benutzer `MES_REPL` (die „Replikation") die Tabelle `BAUGRUPPE`. Die Kette füllt sich von hinten nach vorn:

- Oracle meldet sofort rund 50 blockierte Sessions.
- Der JDBC-Pool steht bei 50/50, das Alter der ältesten ausgeliehenen Connection wächst Sekunde für Sekunde.
- Der Bean-Pool `BaugruppeService` steht bei 50/50.
- Die HTTP-Threads steigen stark – bei niedriger CPU.
- Nach 30 s scheitern die übrigen Requests mit `BEAN_POOL_TIMEOUT` (HTTP 503), auch die reinen Lese-Requests.
- HAProxy staut, der Stammdatenabgleich-Timer hängt mit.

Auffällig: `WaitCount` des JDBC-Pools bleibt nahe 0, eine `PoolExhaustedException` taucht nirgends auf. Nach Freigabe der Sperre ist alles in unter 5 s wieder normal.""",
        "warum": """Jede Buchung schreibt in `BAUGRUPPE` und wartet gegen `LOCK TABLE` in Oracle – mit Connection und Bean-Instanz in der Hand. Beendet wird diese Wartezeit erst durch `oracle.jdbc.ReadTimeout`, beim Kunden 60 Minuten. Im Thread-Dump stehen diese Threads auf `RUNNABLE` (Socket-Read), nicht auf `BLOCKED`.

Die ersten 50 Requests belegen alle 50 Instanzen von `BaugruppeService`. Request 51 scheitert deshalb nicht am JDBC-Pool, sondern schon am Bean-Pool: Er wartet `accessTimeout = 30 s` auf eine freie Instanz. Weil Bean-Pool und JDBC-Pool gleich groß sind, greift der Bean-Pool zuerst – deshalb nie „PoolExhausted".

Lese-Requests warten in Oracle nie auf Sperren. Sie laufen aber durch dieselbe Bean-Klasse und bekommen keine Instanz – so koppelt der Bean-Pool Lesen an Schreiben. Jeder wartende Aufrufer hält währenddessen einen HTTP-Thread fest.""",
        "verhindern": """Die Sperre selbst lässt sich nur an der Quelle beheben: Warum sperrt die Replikation die ganze Tabelle, und wie lange? Konfiguration macht den Ausfall kürzer und sichtbar:

- `tomee.xml`, beide DataSources: `oracle.jdbc.ReadTimeout=3600000` → `300000`. Der einzige Mechanismus, der eine Wartezeit auf `LOCK TABLE` beendet.
- `tomee.xml`, Default Stateless Container: `accessTimeout` 30 s → 5 s. Wartende scheitern schneller und geben ihren HTTP-Thread frei.
- `tomee.xml`: `maxWaitTime = -1` wirkt nicht (effektiv 30 s) – ersetzen durch `maxWait = 5000`.
- `server.xml`: Executor aktivieren (`maxThreads 100`, `maxQueueSize 200`) – Überlast wird sofort mit 503 abgewiesen.

Nicht hilfreich: mehr Connections oder Beans. 100 statt 50 bedeuten nur 100 blockierte Oracle-Sessions. Im Code: Lesen und Schreiben auf getrennte Bean-Klassen verteilen.""",
    },
    "S02": {
        "passiert": """Viele langsame Abfragen (Standard 40 × 45 s) laufen gegen `Master_MES_Connection` mit 20 Connections. Der Pool steht sofort bei 20/20, `WaitCount` steigt. Nach genau 30 s bekommen die Wartenden eine `PoolExhaustedException … in 30 seconds`. In JMX steht bei `MaxWait` der Wert 30000 – obwohl in der `tomee.xml` `maxWaitTime = -1` steht.""",
        "warum": """20 Connections, 40 Aufrufer, jede Connection 45 s belegt – die Hälfte muss warten. Die Kundendatei will „unbegrenzt warten" mit `maxWaitTime = -1`. Diesen Namen übernimmt TomEE 10.1.2 mit tomcat-jdbc aber nicht; es gilt der Pool-Default `maxWait = 30000`. Die Konfiguration wirkt also nicht so, wie sie gelesen wird – in keine Richtung.""",
        "verhindern": """- `tomee.xml`: `maxWaitTime` entfernen, `maxWait = 5000` (nativer Name, Millisekunden) setzen. Fehler nach 5 s statt 30 s, Threads 25 s früher frei.
- `tomee.xml`: `ReadTimeout` 60 min → 5 min – keine Abfrage hält eine Master-Connection länger als 5 min.
- `tomee.xml`: `SlowQueryReportJmx` – zeigt, welche Abfragen den Pool blockieren.
- `maxActive` erst nach Messung erhöhen: nur wenn `WaitCount` im Normalbetrieb > 0 ist und die Master-DB weitere Sessions verträgt.

Beim Kunden klären: Die Notiz „150 Verbindungen eingestellt" passt nicht zu `maxActive` 50 + 20 in der `tomee.xml`.""",
    },
    "S03": {
        "passiert": """Mehr Aufrufer als Bean-Instanzen (Standard: 80 bei 50), jede Bean arbeitet 40 s – ganz ohne Datenbank. `InstancesActive` steht bei 50/50, `AvailablePermits` bei 0. Nach genau 30 s bekommen die 30 Wartenden `BEAN_POOL_TIMEOUT`, `AccessTimeouts` steigt um 30. Die HTTP-Threads sind währenddessen alle belegt.""",
        "warum": """`maxSize = 50` mit `strictPooling = true`: Es gibt nie mehr als 50 Instanzen dieser Bean-Klasse. Der 51. Aufrufer wartet `accessTimeout = 30 s` und bekommt dann eine `ConcurrentAccessTimeoutException`. Da alle Instanzen 40 s belegt sind, hat er keine Chance. Das ist die Grenze „pro Fassade 50 Beans" aus dem Kundengespräch – sie gilt je Bean-Klasse, nicht für den ganzen Container.""",
        "verhindern": """- `tomee.xml`, Default Stateless Container: `accessTimeout` 30 s → 5 s. Wer 5 s keine Bean bekommt, bekommt sie auch in 30 s nicht – hält aber so lange einen HTTP-Thread fest.
- `maxSize` nur erhöhen, wenn die Bean auf etwas wartet, das mehr Parallelität verträgt. Bei DB-Zugriff sollte `maxSize` ≤ `maxActive` bleiben, sonst wandert der Stau in den JDBC-Pool.
- `strictPooling = true` lassen – `false` hebt die Grenze auf und lässt den Stau ungebremst in die Datenbank.
- Die eigentliche Ursache ist die Laufzeit der Bean.""",
    },
    "S04": {
        "passiert": """300 langsame Requests (20 s) über HAProxy – ohne Datenbank, ohne Bean-Pool. 200 HTTP-Threads sind belegt (Default `maxThreads`). HAProxy (`maxconn 200` je Server) hält den Rest in seiner Queue und antwortet nach 30 s mit 503 – in der Demo tausendfach. Die CPU ist niedrig. Die HTTP-Diagnose des Core antwortet nicht mehr, JConsole und die HAProxy-Statistik funktionieren weiter.""",
        "warum": """Die `server.xml` des Kunden hat keinen Executor und keine Grenzen gesetzt – es gelten stille Defaults: `maxThreads 200`, `maxConnections 8192`, `acceptCount 100`. Sind alle Threads belegt, wartet jede weitere Verbindung. Ohne `maxconn` am HAProxy würde Tomcat bis zu 8192 Verbindungen annehmen und still in seine Warteschlange legen.

Die Diagnose über HTTP braucht selbst einen HTTP-Thread – sie fällt genau dann aus, wenn man sie braucht.""",
        "verhindern": """- `server.xml`: Executor aktivieren – `maxThreads 100`, `minSpareThreads 10`, `maxQueueSize 200` – und am Connector `executor="tomcatThreadPool"`. 100 Threads reichen, weil dahinter ohnehin nur 50 Beans und 50 Connections warten. Darüber wird sofort abgewiesen statt still gestaut.
- `server.xml`, Connector: `maxConnections 2000`, `acceptCount 100`, `keepAliveTimeout 15000` bewusst setzen.
- HAProxy: `maxconn` je Server ≤ `maxThreads` + Queue.
- `maxThreads` erhöhen hilft nur, wenn CPU, Beans und Connections frei sind – bei S01 bringt es nichts.
- Monitoring nie nur über den Pfad, den es überwacht: JMX-Port, HAProxy-Statistik.""",
    },
    "S05": {
        "passiert": """Aufgaben werden in Schritten an `BatchHandling` gegeben (Kunde: Core 100, Queue 1000, Max 10000):

- 100 Aufgaben → 100 Threads.
- 1000 Aufgaben → weiterhin 100 Threads, 900 in der Queue.
- 1100 Aufgaben → 100 Threads, Queue voll.
- 1500 Aufgaben → plötzlich 500 Threads.

Die neuen Threads bearbeiten die neuesten Aufgaben – die 1000 ältesten warten weiter in der Queue.

Mit Executor = `MslHandling` und z. B. 1050 Aufgaben zeigt sich die andere Seite: Core = Max = 10, Queue 1000 – 10 laufen, 1000 warten, 40 werden abgelehnt (`mes_executor_abgelehnt_total`).""",
        "warum": """Ein `ManagedExecutorService` ist ein `ThreadPoolExecutor`. Seine Regel: bis `Core` für jede Aufgabe ein neuer Thread, danach in die Queue, und erst wenn die Queue voll ist, weitere Threads bis `Max`. Thread 101 entsteht also erst bei Aufgabe 1101.

Im Normalfall ist `Max = 10000` damit wirkungslos. Im Ernstfall schlägt es um: bis zu 10 000 Threads auf 4 Kernen, jeder mit eigenem Stack, alle im Wettbewerb um 50 DB-Connections – Kontextwechsel, Speicher außerhalb des Heaps, im schlimmsten Fall `unable to create native thread` oder OOM-Kill. Die Demo begrenzt das mit `pids_limit 4096`, der Kunde nicht.

Ist `Max = Core` und die Queue voll, gibt es keinen weiteren Thread: Die nächste Aufgabe bekommt eine `RejectedExecutionException`. TomEE zählt Ablehnungen nicht selbst – ohne eigene Metrik und ohne Behandlung im Code ist die Aufgabe still verloren.""",
        "verhindern": """- `tomee.xml`, `BatchHandling`: `Core = Max = 16`, `Queue = 5000`. Kein Umschlagpunkt mehr, die Last staut sich sichtbar in der Queue (`tomee_executor_queuesize`) statt im Scheduler des Betriebssystems.
- Herleitung: Braucht jede Aufgabe eine DB-Connection, darf der Executor nur einen Teil von `maxActive` belegen, sonst warten die Online-Requests. Bei CPU-lastigen Aufgaben 1–2 × Kernzahl.
- Gleiches Muster bei `FileWatcher` (Core 10, Max 20: Max greift praktisch nie) und `GeneralThreadPool` (250 fest).
- `docker run --pids-limit` als letzte Schutzgrenze.
- Ablehnungen: `RejectedExecutionException` im Code fangen und loggen; `Queue` nur vergrößern, wenn die Aufgaben die Wartezeit fachlich vertragen. Alarme `ExecutorQueueStaut` und `ExecutorLehntAb`.""",
    },
    "S06": {
        "passiert": """Zwei Ursachen sind wählbar:

- `sperre` (Kundenfall, Standard): Keine Last, nur eine Tabellensperre. Der minütliche Stammdatenabgleich läuft in die Sperre, jede Minute hängt ein weiterer Lauf. Nach drei Minuten steht der EJB-Heartbeat – in der Demo bis zu 98 s ohne Lauf. Oracle zeigt mehrere blockierte Sessions (EJB- und Quartz-Abgleiche). Quartz tickt noch, weil es einen eigenen Pool mit 5 Threads hat.
- `lange-laeufe`: Drei lange EJB-Läufe (oder fünf Quartz-Läufe) belegen alle Threads des Schedulers direkt, ganz ohne Datenbank. Der Heartbeat (Soll alle 10 s) läuft nicht mehr.

In beiden Fällen: „Sekunden seit letztem Lauf" steigt linear – kein Fehler, keine Exception, kein Logeintrag. Nach Ende der Störung läuft alles sofort wieder, im Nachhinein ist nichts zu sehen. Misfires zählt Quartz erst danach – und nur bei mehr als 60 s Verspätung.""",
        "warum": """TomEE führt `@Schedule`- und `TimerService`-Timer intern über Quartz aus – mit einem einzigen Thread-Pool für alle Timer der JVM. Seine Größe ist `openejb.timer.pool.size`, Default 3. Sind drei Läufe aktiv, wartet jeder weitere fällige Timer auf einen freien Thread – auch solche, die mit der Datenbank nichts zu tun haben. Das ist das Kundensymptom „Cronjob läuft manchmal nicht, Timer hat keine Zeit bekommen".

Im Kundenfall hält jeder Abgleich eine Connection und wartet in Oracle auf die Sperre, bis `ReadTimeout` (Kunde 60 min). Rechenregel: Ein Timer mit Intervall i, der t lang hängt, belegt ohne Überlappungsschutz t / i Threads – bei 60 s Intervall und 3600 s ReadTimeout bis zu 60.

Quartz zählt einen Misfire erst, wenn ein Termin länger als `misfireThreshold` (60 s) zurückliegt und wieder ein Thread frei ist. Der Misfire-Zähler ist deshalb ein Nachweis im Nachhinein, kein Frühwarner.""",
        "verhindern": """Der Hebel ist die Kombination:

- `tomee.xml`: `ReadTimeout` 60 min → 5 min – ein hängender Lauf gibt seinen Thread nach 5 min frei.
- Im Code: Überlappungsschutz – kein neuer Lauf, solange der vorige läuft. Dann hängt höchstens ein Thread je Timer.
- Im Code: Timer nur auslösen lassen und die Arbeit an einen Executor abgeben – der Timer-Thread ist nach Millisekunden wieder frei.
- `conf/system.properties` oder `JAVA_OPTS` (nicht `tomee.xml`): `openejb.timer.pool.size = 10` gibt mehr Puffer, löst das Problem allein aber nicht. In der Demo: `TIMER_POOL_SIZE` in `.env`. Quartz: `org.quartz.threadPool.threadCount`.
- Monitoring: Heartbeat-Metrik je Timer mit Alarm bei 2× und 4× Soll-Intervall (`SchedulerVerspaetet`, `SchedulerTicktNicht`) – ohne sie ist das Problem unsichtbar.

Offene Frage an den Kunden: Ist das „erhöht von 1/5 auf 10" der Wert `openejb.timer.pool.size`?""",
    },
    "S07": {
        "passiert": """Eine Transaktion mit 30 s Timeout sperrt Baugruppe 42 und arbeitet 90 s. Fünf Buchungen auf Baugruppe 42 warten – die ganzen 90 s, nicht 30. Oracle zeigt 5 blockierte Sessions durch die eigene Anwendung. Nach 60 s erscheint im Log „Transaktion läuft seit … s". Das Ergebnis: zurückgerollt – nach 90 s. Die TomEE-MBean zeigt als Default-Timeout „10 MINUTES", effektiv gelten 14 400 s.""",
        "warum": """Ein Transaction Timeout im TX-Manager markiert die Transaktion nur als „rollback only". Der Thread arbeitet weiter, hält Sperren und Connection, bis die Methode zurückkehrt. Erst dann wird zurückgerollt. Der Timeout verhindert also das Commit, nicht das Blockieren.

Der Kunde hat 14 400 s (4 h) eingestellt. Das bewirkt nur, dass zu lange Transaktionen nach 4 h zurückgerollt statt committet werden. Und die MBean zeigt einen falschen Wert – nicht jede MBean zeigt, was gilt.""",
        "verhindern": """- `tomee.xml`: `defaultTransactionTimeoutSeconds` 14400 → 900. Lange Batch-Jobs setzen ihren Timeout gezielt selbst (`UserTransaction.setTransactionTimeout`).
- `tomee.xml`: `ReadTimeout` 60 min → 5 min – das bricht die wartenden Buchungen tatsächlich ab.
- Monitoring: laufende Transaktionen über einer Schwelle loggen und zählen (Demo: `mes_transaktionen_ueberschwelle`), für Produktion z. B. ab 3600 s – das erfüllt den Kundenwunsch „Transaction Timeouts loggen".
- Im Code: Transaktionen kurz halten, lange Arbeit außerhalb der Transaktion erledigen.""",
    },
    "S08": {
        "passiert": """Clients ohne Cookie rufen eine Seite auf, die eine Session anlegt. Jeder Request erzeugt eine neue Session (hier 50 KB). `tomcat_sessions_activesessions` steigt linear mit der Request-Rate, der Heap steigt mit – und bleibt 30 Minuten so, auch wenn die Last aufhört.""",
        "warum": """Ohne Cookie erkennt Tomcat den Client nicht wieder und legt bei jedem `getSession()` eine neue Session an. Sie lebt bis zum Session-Timeout (Default 30 min), auch wenn niemand sie je wieder benutzt. Typische Verursacher in der Praxis: Health-Checks, Maschinen-Clients und Monitoring-Abfragen, die versehentlich eine Session erzeugen. Folge: GC-Druck bis zum OutOfMemoryError.""",
        "verhindern": """Keine Stellschraube in `tomee.xml`/`server.xml`:

- `WEB-INF/web.xml`: `<session-timeout>` auf den fachlich kürzesten vertretbaren Wert.
- `context.xml`: `<Manager maxActiveSessions="…"/>` als Obergrenze – darüber lehnt Tomcat neue Sessions ab.
- Im Code: `request.getSession(false)` für zustandslose Schnittstellen und Health-Checks.
- Monitoring: aktive Sessions als Trend.""",
    },
    "S09": {
        "passiert": """Die Facade (Demo: `-Xmx2500m` bei 700 MB Container-Limit; Kunde: `-Xmx7168M` bei `-m 2000m`) belegt Heap in 100-MB-Schritten. Der Container-Speicher erreicht das Limit, danach wird geswappt – in der Demo waren bis ca. 800 MB belegt. Dann ist der Prozess schlagartig weg: HTTP-Verbindung abgebrochen, Exit 137, kein OutOfMemoryError, kein Logeintrag. Die Restart-Policy startet neu, `OOMKilled` steht danach wieder auf `false`.""",
        "warum": """Die JVM plant mit einem Heap, der 3,6-mal so groß ist wie das Container-Limit. Sie sieht keinen Grund, aggressiv aufzuräumen – sie hat ja noch Heap. Irgendwann überschreitet der Prozess das Limit, und der Kernel beendet ihn mit SIGKILL. Die JVM kann das nicht melden. Dass mehr als das Limit belegt werden konnte, liegt am Swap: `docker run -m` ohne `--memory-swap` erlaubt zusätzlich Swap in Höhe des Limits.

Nebenbefund: Die Facade setzt JMX auf Port 9300, gemappt ist 9400 – JConsole scheitert, obwohl der Port offen aussieht.""",
        "verhindern": """Keine Stellschraube in `tomee.xml`/`server.xml`:

- `JAVA_OPTS`: `-Xmx` ≤ ~70 % des Container-Limits, beim Kunden also `-Xmx1400M` (und `-Xms` ≤ `-Xmx`). Alternativ `-XX:MaxRAMPercentage=70` statt festem `-Xmx`.
- Oder `-m` erhöhen – nur, wenn die Facade den Heap wirklich braucht. Auf dem Host (32 GB) sind mit Core 10 g und FileProcessing 12 g schon viel vergeben.
- `docker run --memory-swap` = `-m`.
- JMX-Port auf 9400 korrigieren.
- Monitoring von außen: `up == 0`, Wechsel von `process_start_time_seconds`, Neustart-Zähler, `docker events --filter event=oom`, Container-Speicher über cAdvisor.""",
    },
    "S10": {
        "passiert": """300 Socket-Clients verbinden sich mit FileProcessing, dazu werden in Schritten je 500 Dateien geöffnet und nicht geschlossen. Die offenen File Descriptors steigen je Schritt um 500 (in der Demo 783 → 1283 → 1783 → 2283 …) – bei einem Limit von 4096. Ab 70 % feuert der Alarm `FileDescriptorsHoch`.""",
        "warum": """Jede offene Datei, jede Socket-Verbindung (HTTP, TCP-Schnittstelle, JDBC, JMS) und jede geladene JAR belegt einen File Descriptor. Nicht geschlossene Dateien belegen ihn dauerhaft. Beim Limit scheitert jede Operation, die einen braucht: „Too many open files" – keine neuen Verbindungen, keine DB-Connections, keine Logdateien.

Die Antwort auf „440 gut? 500 gut?": Es kommt auf das Verhältnis zum Limit, den Trend im Leerlauf und das Verhalten nach der Last an. 500 von 524 288 ist nichts, 500 von 1024 ist die Hälfte.""",
        "verhindern": """- Istwert erheben: `MaxFileDescriptorCount` in JConsole – beim Kunden unbekannt.
- `docker run --ulimit nofile=…` mit ausreichend Luft (Startwert: ≥ 4 × Spitzenwert).
- `server.xml`, Connector: `maxConnections` bewusst setzen (Startwert 2000) – begrenzt die HTTP-Verbindungen und damit deren FDs.
- Lese-Timeout im Socket-Server (Demo: `SOCKET_TIMEOUT_MS` in `.env`), damit stille Verbindungen Thread und FD freigeben.
- Im Code: `try-with-resources` für alle Streams.""",
    },
}
