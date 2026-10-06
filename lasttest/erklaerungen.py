"""
erklaerungen.py – ausführliche Erklärung je Szenario (S01–S19) für die Laststeuerung.

Die Oberfläche zeigt die Texte zugeklappt („Auflösung"), damit sie im Workshop
nicht vorwegnehmen, was die Teilnehmer selbst herausfinden sollen.

Je Szenario drei Abschnitte:
  passiert    – was im System geschieht, in der Reihenfolge, in der man es sieht
  warum       – der Mechanismus dahinter
  verhindern  – was hilft (und was nicht); Konfiguration mit Zollner-Wert → Startwert

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
        "warum": """Jede Buchung schreibt in `BAUGRUPPE` und wartet gegen `LOCK TABLE` in Oracle – mit Connection und Bean-Instanz in der Hand. Beendet wird diese Wartezeit erst durch `oracle.jdbc.ReadTimeout`, bei Zollner 60 Minuten. Im Thread-Dump stehen diese Threads auf `RUNNABLE` (Socket-Read), nicht auf `BLOCKED`.

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
        "warum": """20 Connections, 40 Aufrufer, jede Connection 45 s belegt – die Hälfte muss warten. Die `tomee.xml` von Zollner will „unbegrenzt warten" mit `maxWaitTime = -1`. Diesen Namen übernimmt TomEE 10.1.2 mit tomcat-jdbc aber nicht; es gilt der Pool-Default `maxWait = 30000`. Die Konfiguration wirkt also nicht so, wie sie gelesen wird – in keine Richtung.""",
        "verhindern": """- `tomee.xml`: `maxWaitTime` entfernen, `maxWait = 5000` (nativer Name, Millisekunden) setzen. Fehler nach 5 s statt 30 s, Threads 25 s früher frei.
- `tomee.xml`: `ReadTimeout` 60 min → 5 min – keine Abfrage hält eine Master-Connection länger als 5 min.
- `tomee.xml`: `SlowQueryReportJmx` – zeigt, welche Abfragen den Pool blockieren.
- `maxActive` erst nach Messung erhöhen: nur wenn `WaitCount` im Normalbetrieb > 0 ist und die Master-DB weitere Sessions verträgt.""",
    },
    "S03": {
        "passiert": """Mehr Aufrufer als Bean-Instanzen (Standard: 80 bei 50), jede Bean arbeitet 40 s – ganz ohne Datenbank. `InstancesActive` steht bei 50/50, `AvailablePermits` bei 0. Nach genau 30 s bekommen die 30 Wartenden `BEAN_POOL_TIMEOUT`, `AccessTimeouts` steigt um 30. Die HTTP-Threads sind währenddessen alle belegt.""",
        "warum": """`maxSize = 50` mit `strictPooling = true`: Es gibt nie mehr als 50 Instanzen dieser Bean-Klasse. Der 51. Aufrufer wartet `accessTimeout = 30 s` und bekommt dann eine `ConcurrentAccessTimeoutException`. Da alle Instanzen 40 s belegt sind, hat er keine Chance. Das ist die Grenze „pro Fassade 50 Beans" aus dem Vorgespräch – sie gilt je Bean-Klasse, nicht für den ganzen Container.""",
        "verhindern": """- `tomee.xml`, Default Stateless Container: `accessTimeout` 30 s → 5 s. Wer 5 s keine Bean bekommt, bekommt sie auch in 30 s nicht – hält aber so lange einen HTTP-Thread fest.
- `maxSize` nur erhöhen, wenn die Bean auf etwas wartet, das mehr Parallelität verträgt. Bei DB-Zugriff sollte `maxSize` ≤ `maxActive` bleiben, sonst wandert der Stau in den JDBC-Pool.
- `strictPooling = true` lassen – `false` hebt die Grenze auf und lässt den Stau ungebremst in die Datenbank.
- Die eigentliche Ursache ist die Laufzeit der Bean.""",
    },
    "S04": {
        "passiert": """300 langsame Requests (20 s) über HAProxy – ohne Datenbank, ohne Bean-Pool. 200 HTTP-Threads sind belegt (Default `maxThreads`). HAProxy (`maxconn 200` je Server) hält den Rest in seiner Queue und antwortet nach 30 s mit 503 – in der Demo tausendfach. Die CPU ist niedrig. Die HTTP-Diagnose des Core antwortet nicht mehr, JConsole und die HAProxy-Statistik funktionieren weiter.""",
        "warum": """Die `server.xml` von Zollner hat keinen Executor und keine Grenzen gesetzt – es gelten stille Defaults: `maxThreads 200`, `maxConnections 8192`, `acceptCount 100`. Sind alle Threads belegt, wartet jede weitere Verbindung. Ohne `maxconn` am HAProxy würde Tomcat bis zu 8192 Verbindungen annehmen und still in seine Warteschlange legen.

Die Diagnose über HTTP braucht selbst einen HTTP-Thread – sie fällt genau dann aus, wenn man sie braucht.""",
        "verhindern": """- `server.xml`: Executor aktivieren – `maxThreads 100`, `minSpareThreads 10`, `maxQueueSize 200` – und am Connector `executor="tomcatThreadPool"`. 100 Threads reichen, weil dahinter ohnehin nur 50 Beans und 50 Connections warten. Darüber wird sofort abgewiesen statt still gestaut.
- `server.xml`, Connector: `maxConnections 2000`, `acceptCount 100`, `keepAliveTimeout 15000` bewusst setzen.
- HAProxy: `maxconn` je Server ≤ `maxThreads` + Queue.
- `maxThreads` erhöhen hilft nur, wenn CPU, Beans und Connections frei sind – bei S01 bringt es nichts.
- Monitoring nie nur über den Pfad, den es überwacht: JMX-Port, HAProxy-Statistik.""",
    },
    "S05": {
        "passiert": """Aufgaben werden in Schritten an `BatchHandling` gegeben (Zollner: Core 100, Queue 1000, Max 10000):

- 100 Aufgaben → 100 Threads.
- 1000 Aufgaben → weiterhin 100 Threads, 900 in der Queue.
- 1100 Aufgaben → 100 Threads, Queue voll.
- 1500 Aufgaben → plötzlich 500 Threads.

Die neuen Threads bearbeiten die neuesten Aufgaben – die 1000 ältesten warten weiter in der Queue.

Mit Executor = `MslHandling` und z. B. 1050 Aufgaben zeigt sich die andere Seite: Core = Max = 10, Queue 1000 – 10 laufen, 1000 warten, 40 werden abgelehnt (`mes_executor_abgelehnt_total`).""",
        "warum": """Ein `ManagedExecutorService` ist ein `ThreadPoolExecutor`. Seine Regel: bis `Core` für jede Aufgabe ein neuer Thread, danach in die Queue, und erst wenn die Queue voll ist, weitere Threads bis `Max`. Thread 101 entsteht also erst bei Aufgabe 1101.

Im Normalfall ist `Max = 10000` damit wirkungslos. Im Ernstfall schlägt es um: bis zu 10 000 Threads auf 4 Kernen, jeder mit eigenem Stack, alle im Wettbewerb um 50 DB-Connections – Kontextwechsel, Speicher außerhalb des Heaps, im schlimmsten Fall `unable to create native thread` oder OOM-Kill. Die Demo begrenzt das mit `pids_limit 4096`, bei Zollner ist keine solche Grenze gesetzt.

Ist `Max = Core` und die Queue voll, gibt es keinen weiteren Thread: Die nächste Aufgabe bekommt eine `RejectedExecutionException`. TomEE zählt Ablehnungen nicht selbst – ohne eigene Metrik und ohne Behandlung im Code ist die Aufgabe still verloren.""",
        "verhindern": """- `tomee.xml`, `BatchHandling`: `Core = Max = 16`, `Queue = 5000`. Kein Umschlagpunkt mehr, die Last staut sich sichtbar in der Queue (`tomee_executor_queuesize`) statt im Scheduler des Betriebssystems.
- Herleitung: Braucht jede Aufgabe eine DB-Connection, darf der Executor nur einen Teil von `maxActive` belegen, sonst warten die Online-Requests. Bei CPU-lastigen Aufgaben 1–2 × Kernzahl.
- Gleiches Muster bei `FileWatcher` (Core 10, Max 20: Max greift praktisch nie) und `GeneralThreadPool` (250 fest).
- `docker run --pids-limit` als letzte Schutzgrenze.
- Ablehnungen: `RejectedExecutionException` im Code fangen und loggen; `Queue` nur vergrößern, wenn die Aufgaben die Wartezeit fachlich vertragen. Alarme `ExecutorQueueStaut` und `ExecutorLehntAb`.""",
    },
    "S06": {
        "passiert": """Zwei Ursachen sind wählbar:

- `sperre` (Zollner-Fall, Standard): Keine Last, nur eine Tabellensperre. Der minütliche Stammdatenabgleich läuft in die Sperre, jede Minute hängt ein weiterer Lauf. Nach drei Minuten steht der EJB-Heartbeat – in der Demo bis zu 98 s ohne Lauf. Oracle zeigt mehrere blockierte Sessions (EJB- und Quartz-Abgleiche). Quartz tickt noch, weil es einen eigenen Pool mit 5 Threads hat.
- `lange-laeufe`: Drei lange EJB-Läufe (oder fünf Quartz-Läufe) belegen alle Threads des Schedulers direkt, ganz ohne Datenbank. Der Heartbeat (Soll alle 10 s) läuft nicht mehr.

In beiden Fällen: „Sekunden seit letztem Lauf" steigt linear – kein Fehler, keine Exception, kein Logeintrag. Nach Ende der Störung läuft alles sofort wieder, im Nachhinein ist nichts zu sehen. Misfires zählt Quartz erst danach – und nur bei mehr als 60 s Verspätung.""",
        "warum": """TomEE führt `@Schedule`- und `TimerService`-Timer intern über Quartz aus – mit einem einzigen Thread-Pool für alle Timer der JVM. Seine Größe ist `openejb.timer.pool.size`, Default 3. Sind drei Läufe aktiv, wartet jeder weitere fällige Timer auf einen freien Thread – auch solche, die mit der Datenbank nichts zu tun haben. Das ist das gemeldete Symptom „Cronjob läuft manchmal nicht, Timer hat keine Zeit bekommen".

Im Zollner-Fall hält jeder Abgleich eine Connection und wartet in Oracle auf die Sperre, bis `ReadTimeout` (Zollner 60 min). Rechenregel: Ein Timer mit Intervall i, der t lang hängt, belegt ohne Überlappungsschutz t / i Threads – bei 60 s Intervall und 3600 s ReadTimeout bis zu 60.

Quartz zählt einen Misfire erst, wenn ein Termin länger als `misfireThreshold` (60 s) zurückliegt und wieder ein Thread frei ist. Der Misfire-Zähler ist deshalb ein Nachweis im Nachhinein, kein Frühwarner.""",
        "verhindern": """Der Hebel ist die Kombination:

- `tomee.xml`: `ReadTimeout` 60 min → 5 min – ein hängender Lauf gibt seinen Thread nach 5 min frei.
- Im Code: Überlappungsschutz – kein neuer Lauf, solange der vorige läuft. Dann hängt höchstens ein Thread je Timer.
- Im Code: Timer nur auslösen lassen und die Arbeit an einen Executor abgeben – der Timer-Thread ist nach Millisekunden wieder frei.
- `conf/system.properties` oder `JAVA_OPTS` (nicht `tomee.xml`): `openejb.timer.pool.size = 10` gibt mehr Puffer, löst das Problem allein aber nicht. In der Demo: `TIMER_POOL_SIZE` in `.env`. Quartz: `org.quartz.threadPool.threadCount`.
- Monitoring: Heartbeat-Metrik je Timer mit Alarm bei 2× und 4× Soll-Intervall (`SchedulerVerspaetet`, `SchedulerTicktNicht`) – ohne sie ist das Problem unsichtbar.""",
    },
    "S07": {
        "passiert": """Eine Transaktion mit 30 s Timeout sperrt Baugruppe 42 und arbeitet 90 s. Fünf Buchungen auf Baugruppe 42 warten – die ganzen 90 s, nicht 30. Oracle zeigt 5 blockierte Sessions durch die eigene Anwendung. Nach 60 s erscheint im Log „Transaktion läuft seit … s". Das Ergebnis: zurückgerollt – nach 90 s. Die TomEE-MBean zeigt als Default-Timeout „10 MINUTES", effektiv gelten 14 400 s.""",
        "warum": """Ein Transaction Timeout im TX-Manager markiert die Transaktion nur als „rollback only". Der Thread arbeitet weiter, hält Sperren und Connection, bis die Methode zurückkehrt. Erst dann wird zurückgerollt. Der Timeout verhindert also das Commit, nicht das Blockieren.

Bei Zollner sind 14 400 s (4 h) eingestellt. Das bewirkt nur, dass zu lange Transaktionen nach 4 h zurückgerollt statt committet werden. Und die MBean zeigt einen falschen Wert – nicht jede MBean zeigt, was gilt.""",
        "verhindern": """- `tomee.xml`: `defaultTransactionTimeoutSeconds` 14400 → 900. Lange Batch-Jobs setzen ihren Timeout gezielt selbst (`UserTransaction.setTransactionTimeout`).
- `tomee.xml`: `ReadTimeout` 60 min → 5 min – das bricht die wartenden Buchungen tatsächlich ab.
- Monitoring: laufende Transaktionen über einer Schwelle loggen und zählen (Demo: `mes_transaktionen_ueberschwelle`), für Produktion z. B. ab 3600 s – das erfüllt die Anforderung „Transaction Timeouts loggen".
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
        "passiert": """Die Facade (Demo: `-Xmx2500m` bei 700 MB Container-Limit; Zollner: `-Xmx7168M` bei `-m 2000m`) belegt Heap in 100-MB-Schritten. Der Container-Speicher erreicht das Limit, danach wird geswappt – in der Demo waren bis ca. 800 MB belegt. Dann ist der Prozess schlagartig weg: HTTP-Verbindung abgebrochen, Exit 137, kein OutOfMemoryError, kein Logeintrag. Die Restart-Policy startet neu, `OOMKilled` steht danach wieder auf `false`.""",
        "warum": """Die JVM plant mit einem Heap, der 3,6-mal so groß ist wie das Container-Limit. Sie sieht keinen Grund, aggressiv aufzuräumen – sie hat ja noch Heap. Irgendwann überschreitet der Prozess das Limit, und der Kernel beendet ihn mit SIGKILL. Die JVM kann das nicht melden. Dass mehr als das Limit belegt werden konnte, liegt am Swap: `docker run -m` ohne `--memory-swap` erlaubt zusätzlich Swap in Höhe des Limits.

Nebenbefund: Die Facade setzt JMX auf Port 9300, gemappt ist 9400 – JConsole scheitert, obwohl der Port offen aussieht.""",
        "verhindern": """Keine Stellschraube in `tomee.xml`/`server.xml`:

- `JAVA_OPTS`: `-Xmx` ≤ ~70 % des Container-Limits, bei Zollner also `-Xmx1400M` (und `-Xms` ≤ `-Xmx`). Alternativ `-XX:MaxRAMPercentage=70` statt festem `-Xmx`.
- Oder `-m` erhöhen – nur, wenn die Facade den Heap wirklich braucht. Auf dem Host (32 GB) sind mit Core 10 g und FileProcessing 12 g schon viel vergeben.
- `docker run --memory-swap` = `-m`.
- JMX-Port auf 9400 korrigieren.
- Monitoring von außen: `up == 0`, Wechsel von `process_start_time_seconds`, Neustart-Zähler, `docker events --filter event=oom`, Container-Speicher über cAdvisor.""",
    },
    "S10": {
        "passiert": """300 Socket-Clients verbinden sich mit FileProcessing, dazu werden in Schritten je 500 Dateien geöffnet und nicht geschlossen. Die offenen File Descriptors steigen je Schritt um 500 (in der Demo 783 → 1283 → 1783 → 2283 …) – bei einem Limit von 4096. Ab 70 % feuert der Alarm `FileDescriptorsHoch`.""",
        "warum": """Jede offene Datei, jede Socket-Verbindung (HTTP, TCP-Schnittstelle, JDBC, JMS) und jede geladene JAR belegt einen File Descriptor. Nicht geschlossene Dateien belegen ihn dauerhaft. Beim Limit scheitert jede Operation, die einen braucht: „Too many open files" – keine neuen Verbindungen, keine DB-Connections, keine Logdateien.

Die Antwort auf „440 gut? 500 gut?": Es kommt auf das Verhältnis zum Limit, den Trend im Leerlauf und das Verhalten nach der Last an. 500 von 524 288 ist nichts, 500 von 1024 ist die Hälfte.""",
        "verhindern": """- Istwert erheben: `MaxFileDescriptorCount` in JConsole.
- `docker run --ulimit nofile=…` mit ausreichend Luft (Startwert: ≥ 4 × Spitzenwert).
- `server.xml`, Connector: `maxConnections` bewusst setzen (Startwert 2000) – begrenzt die HTTP-Verbindungen und damit deren FDs.
- Lese-Timeout im Socket-Server (Demo: `SOCKET_TIMEOUT_MS` in `.env`), damit stille Verbindungen Thread und FD freigeben.
- Im Code: `try-with-resources` für alle Streams.""",
    },
    "S11": {
        "passiert": """Ein periodischer EJB-Timer auf dem Singleton wird alle 10 s fällig, jeder Lauf braucht 35 s. Was man sieht, hängt vom Überlappungsschutz ab:

- `ohne`: Jeder fällige Lauf startet. Nach wenigen Intervallen sind alle drei Timer-Threads mit Läufen dieses einen Jobs belegt. Der Heartbeat (Soll alle 10 s) bekommt keinen Thread mehr, „Sekunden seit letztem Lauf" steigt – ohne Fehler, ohne Logeintrag.
- `singleton-lock`: Es arbeitet immer nur ein Lauf. Die anderen fälligen Läufe warten auf die Sperre des Singletons – und halten dabei ihren Timer-Thread. Nach 30 s scheitern sie mit `ConcurrentAccessTimeoutException`. Der Heartbeat steht trotzdem.
- `ueberspringen`: Läuft der vorige Lauf noch, entfällt der Termin und wird gezählt. Ein Thread, ein Lauf, der Heartbeat tickt weiter.

Nach dem Stopp arbeiten die laufenden Läufe zu Ende, dann tickt der Heartbeat wieder.""",
        "warum": """Alle EJB-Timer einer JVM teilen sich einen Thread-Pool, Größe `openejb.timer.pool.size`, Default 3. Ein Job, der länger läuft als sein Intervall, belegt ohne Schutz dauerhaft Laufzeit ÷ Intervall Threads – hier 35 ÷ 10, also mehr als es gibt. Er verdrängt damit alle anderen Timer, auch solche, die mit ihm nichts zu tun haben.

Ein `@Singleton` ohne weitere Annotation hat die Sperre `@Lock(WRITE)`. Das verhindert zwar, dass Läufe gleichzeitig arbeiten – aber nicht, dass sie starten. Jeder wartende Lauf sitzt bis zum `AccessTimeout` (Default 30 s) auf einem Timer-Thread. Der vermeintliche Schutz verlagert das Problem nur.""",
        "verhindern": """- Im Code: echten Überlappungsschutz – ist der vorige Lauf noch aktiv, kehrt der neue sofort zurück und wird gezählt.
- Im Code: am `@Singleton` `@AccessTimeout(0)` setzen, dann scheitert ein überlappender Lauf sofort, statt 30 s einen Thread zu halten.
- Im Code: Timer nur auslösen lassen und die Arbeit an einen Executor abgeben.
- Intervall und Laufzeit zusammen betrachten: Die Laufzeit je Job messen (`mes_scheduler_*`) und das Intervall danach wählen.
- `openejb.timer.pool.size` erhöhen (in der Demo `TIMER_POOL_SIZE` in `.env`) gibt Puffer, löst es aber nicht: Bei 35 s Laufzeit und 10 s Intervall sind auch vier Threads dauerhaft belegt.
- Monitoring: Heartbeat je Timer mit den Alarmen `SchedulerVerspaetet` und `SchedulerTicktNicht`, dazu übersprungene Läufe als Zähler.""",
    },
    "S12": {
        "passiert": """Der Core bekommt 15 Nachrichten pro Sekunde in die Queue `MES.EINGANG`. Drei Ursachen sind wählbar:

- `langsam`: Jede Nachricht braucht 1 s. Zehn MDB-Instanzen sind dauerhaft aktiv, mehr als 10 Nachrichten pro Sekunde gehen nicht raus. Die Queue-Tiefe steigt linear, die Wartezeit in der Queue wächst mit.
- `sperre`: Jede Nachricht bucht auf `BAUGRUPPE`, die Tabelle ist gesperrt. Alle zehn Instanzen hängen in Oracle, der Durchsatz fällt auf null.
- `gift`: Ein Teil der Nachrichten scheitert immer. Sie werden wiederholt zugestellt, belegen dabei Instanzen und landen am Ende in der Dead Letter Queue `ActiveMQ.DLQ`.

Nach dem Ende wird der Rückstand abgebaut – Dauer ≈ Tiefe ÷ Durchsatz. Die HTTP-Seite bleibt die ganze Zeit unauffällig.""",
        "warum": """Für die Message-Driven Bean gibt es keine eigene Konfiguration, es gelten die TomEE-Defaults: `InstanceLimit 10` im „Default MDB Container" und `maxSessions 10` im ActiveMQ-Resource-Adapter. Mehr als zehn Nachrichten verarbeitet eine JVM nie gleichzeitig. Der höchste Durchsatz ist damit 10 ÷ Verarbeitungszeit – bei 1 s also 10 pro Sekunde. Alles darüber bleibt im Broker liegen.

Eine Queue entkoppelt: Der Sender merkt nichts, es gibt keinen Fehler und keinen Timeout. Der Stau zeigt sich nur in Tiefe und Alter der Nachrichten.

Wirft `onMessage` eine Exception, wird die Transaktion zurückgerollt und der Broker stellt erneut zu – nach dem ActiveMQ-Default sechsmal, erst dann geht die Nachricht in die Dead Letter Queue. Jede Wiederholung kostet Verarbeitungszeit, die den guten Nachrichten fehlt.""",
        "verhindern": """- Monitoring am Broker: Queue-Tiefe (`activemq_queue_queuesize`), Zufluss gegen Abfluss, Zahl der Konsumenten und die Tiefe der Dead Letter Queue. Die DLQ sollte im Normalbetrieb leer sein.
- Monitoring in der Anwendung: aktive MDB-Instanzen gegen das Limit und die Wartezeit in der Queue (`mes_mdb_*`). 10 von 10 über längere Zeit heißt: Die Verarbeitung ist der Engpass.
- `InstanceLimit` und `maxSessions` nur erhöhen, wenn dahinter Luft ist. Braucht jede Nachricht eine DB-Connection, konkurrieren die MDBs mit den Online-Requests um `maxActive`.
- Gegen die Sperre hilft dasselbe wie in S01: `oracle.jdbc.ReadTimeout` 60 min → 5 min.
- Gift-Nachrichten: Redelivery-Policy bewusst setzen (Anzahl, Abstand) und fachlich unverarbeitbare Nachrichten im Code erkennen und ablegen, statt sie scheitern zu lassen.""",
    },
    "S13": {
        "passiert": """110 Requests pro Sekunde, je 500 ms, laufen über HAProxy auf zwei Cores. Jeder Core hat rund 27 von 50 Beans belegt – beide sehen mit etwa 55 % gesund aus. Dann geht einer in Wartung: `/mes/api/status` antwortet mit 503, HAProxy nimmt ihn nach drei Fehlversuchen (ca. 15 s) heraus. Der verbleibende Core bekommt alles: Bean-Pool 50/50, Aufrufer warten, nach 30 s `BEAN_POOL_TIMEOUT`, die HAProxy-Queue füllt sich. Nach der Freigabe bekommt der Server nach zwei erfolgreichen Checks (ca. 10 s) wieder Last, und alles erholt sich.""",
        "warum": """Little's Law: gleichzeitig belegt ≈ Rate × Antwortzeit, hier 110 × 0,5 s = 55. Auf zwei Server verteilt sind das je 27 von 50, auf einem allein 55 von 50 – mehr als der Bean-Pool hergibt. Die Last, die auf zwei Servern harmlos aussah, passt auf einen nicht mehr.

Eine Warnschwelle von 80 % je Server hätte vorher nie ausgelöst. Bei zwei Servern ist jeder Wert über 50 % bereits eine Aussage: Fällt einer aus, reicht der andere nicht.""",
        "verhindern": """- Warnstufen an N−1 ausrichten: Bei zwei Applikationsservern darf jeder im Normalbetrieb höchstens 50 % seiner engsten Ressource belegen, bei drei 66 %. Engste Ressource ist hier der Bean-Pool, sonst der JDBC-Pool oder die HTTP-Threads.
- Die Rechnung für jede Grenze machen: Rate × Antwortzeit gegen `maxSize`, `maxActive` und `maxThreads`. Die Werte dafür liefert S16.
- Wartung in lastarme Zeiten legen und vorher die Auslastung beider Server prüfen.
- Server über den Health-Check aus der Verteilung nehmen und laufende Requests auslaufen lassen, bevor er gestoppt wird.
- `accessTimeout` 30 s → 5 s: Bei Überlast scheitern die Wartenden schneller und geben ihren HTTP-Thread frei.""",
    },
    "S14": {
        "passiert": """Der Singleton (Demo: `-Xmx1024m` bei 1150 MB Container-Limit; Zollner: `-Xms4048M -Xmx4500M` bei `-m 5000m`) bekommt in Schritten zusätzliche Threads mit belegtem Stack und Direct Buffer. Der Heap bleibt niedrig, die Heap-Kurve ist unauffällig. Die Container-Belegung steigt trotzdem Schritt für Schritt Richtung Limit. Das Szenario hält bei 92 % an – darüber würde der Kernel den Prozess beenden, wie in S09: Exit 137, kein OutOfMemoryError.""",
        "warum": """Eine JVM braucht Speicher außerhalb des Heaps: Metaspace, Code Cache, GC-Strukturen, einen Stack je Thread und Direct Buffer. `-Xmx` begrenzt davon nichts. Das Container-Limit gilt aber für die Summe.

Beim Singleton sind 90 % des Limits für den Heap vorgesehen, für alles andere bleiben rund 500 MB (Demo: 126 MB). JMX zeigt die Zahl der Threads und die Größe der Direct Buffer, aber nicht, wie viel Speicher der Prozess insgesamt belegt. Wer nur auf den Heap schaut, sieht bis zum Kill nichts.""",
        "verhindern": """- `JAVA_OPTS`: `-Xmx` auf etwa 70 % des Container-Limits, wie bei Core und FileProcessing – beim Singleton also rund `-Xmx3500M` bei `-m 5000m`, oder das Limit anheben.
- `JAVA_OPTS`: `-XX:MaxDirectMemorySize` setzen. Ohne die Option dürfen Direct Buffer so groß werden wie `-Xmx`.
- Thread-Zahl begrenzen: feste Executor-Größen in der `tomee.xml` (siehe S05), `docker run --pids-limit` als letzte Grenze.
- Monitoring aus Container-Sicht: Belegung gegen Limit über cAdvisor (Alarm `ContainerSpeicherHoch`) oder `java.lang:type=OperatingSystem` mit `TotalMemorySize` und `FreeMemorySize`.
- Für die Analyse: `-XX:NativeMemoryTracking=summary` und `jcmd 1 VM.native_memory` zeigen, wofür der Speicher außerhalb des Heaps verwendet wird.""",
    },
    "S15": {
        "passiert": """Zwei Grenzen sind wählbar:

- `benutzer`: Oracle erlaubt dem User `MES_LOCAL` höchstens 60 gleichzeitige Sessions. Core und FileProcessing öffnen je 40 langsame Abfragen – jeder bleibt unter seinen 50 Pool-Plätzen, zusammen sind es 80. Wer die 61. Session öffnen will, bekommt sofort `ORA-02391`, gezählt als `DbSitzungslimit`.
- `prozesse`: Ohne künstliche Grenze öffnen Core, FileProcessing und Singleton zusammen so viele Sessions, dass die Prozessgrenze der Datenbank erreicht wird. Neue Verbindungen scheitern für alle – auch für andere Anwendungen und für den DBA.

In beiden Fällen kommt der Fehler sofort, nicht nach 30 s, und der eigene Pool zeigt noch freie Plätze.""",
        "warum": """`maxActive` begrenzt einen Pool in einer JVM. Die Datenbank sieht die Summe: alle Pools, alle Container, alle Applikationsserver, die sich mit demselben User oder an derselben Instanz anmelden. Jeder Pool für sich ist richtig eingestellt, zusammen überschreiten sie die Grenze der Datenbank.

Der Pool wartet nur, wenn er selbst voll ist. Lehnt die Datenbank den Aufbau einer neuen Connection ab, gibt es nichts zu warten – der Fehler geht direkt an den Aufrufer. Deshalb sieht dieser Fall anders aus als S02: kein `WaitCount`, keine `PoolExhaustedException`, `Active` unter `maxActive`.""",
        "verhindern": """- Die Rechnung machen: Summe aller `maxActive` über alle DataSources, Container und Applikationsserver gegen `processes`/`sessions` der Datenbank und gegen `SESSIONS_PER_USER` im Profil – bei der Master-DB über alle Länder.
- `maxActive` aus dieser Summe ableiten, nicht je Pool einzeln festlegen. Eine Erhöhung in einem Pool braucht Platz in der Datenbank.
- Monitoring auf DB-Seite: Sessions je User gegen die Grenze (Demo: `mes_oracle_sitzungen_*`), in Produktion `v$session` und `v$resource_limit`.
- Fehlerart getrennt zählen: `ORA-02391`, `ORA-00018`, `ORA-00020` und `ORA-12516` bedeuten „Datenbank voll", nicht „Pool voll".
- `initialSize`/`minIdle` > 0: Bestehende Connections bleiben nutzbar, auch wenn die Datenbank keine neuen mehr annimmt.""",
    },
    "S16": {
        "passiert": """Das Lastprofil von Zollner läuft über HAProxy: 7 Mio. Requests am Tag sind im Mittel 81 pro Sekunde, davon 43 % Logeinträge, der Rest zu 70 % Lesen und 30 % Buchen, dazu Dateien per TCP. Nichts geht kaputt. Am Ende stehen die Spitzenwerte des Laufs – belegte HTTP-Threads, aktive Connections, aktive Beans, Log-Queue – und die Antwortzeiten je Anfrageart. Mit dem Faktor lässt sich dasselbe Profil für die Spitze fahren.""",
        "warum": """Ohne Baseline lässt sich keine Grenze beurteilen. Ob 50 Connections viel oder wenig sind, hängt davon ab, wie viele im Normalbetrieb und in der Spitze gebraucht werden.

Die Verbindung liefert Little's Law: gleichzeitig belegt ≈ Rate × Antwortzeit. Bei 81 Requests pro Sekunde und 50 ms Antwortzeit sind im Mittel 4 Threads belegt, bei 500 ms schon 40. Die Auslastung hängt an der Antwortzeit stärker als an der Rate – deshalb reißt eine langsame Datenbank die Pools so schnell leer.

Der Tagesmittelwert unterschätzt die Spitze. 7 Mio. am Tag verteilen sich nicht gleichmäßig über 24 Stunden.""",
        "verhindern": """Hier wird nichts verhindert, sondern gemessen – die Grundlage für alle Warnstufen:

- In Produktion über mindestens eine Woche erheben: Spitzenwerte je Pool (JDBC `Active`, Bean `InstancesActive`, HTTP `currentThreadsBusy`, Executor-Queues), Request-Rate und Antwortzeiten.
- Die echte Spitze bestimmen, nicht nur das Tagesmittel: Requests je Minute aus dem Access-Log oder aus HAProxy.
- Warnstufe dort setzen, wo die gemessene Spitze mit Reserve liegt – und bei zwei Applikationsservern so, dass einer allein die Last trägt (S13).
- Die Schwellen in `prometheus/regeln.yml` sind Startwerte. Sie müssen gegen diese Baseline geprüft werden.
- Die Messung nach jeder größeren Änderung wiederholen: neues Release, neuer Standort, mehr Stationen.""",
    },
    "S17": {
        "passiert": """400 Logeinträge pro Sekunde à 8 KB treffen auf einen Schreiber, der nur 100 Zeilen pro Sekunde schafft. Die Log-Queue füllt sich, der Verzug – das Alter des ältesten Eintrags – wächst. Was danach geschieht, entscheidet das Verhalten der Queue:

- `unbegrenzt`: Die Queue nimmt alles an. Der Rückstand liegt im Heap, der Heap steigt, die GC arbeitet mehr.
- `verwerfen`: Ist die Queue voll, gehen Einträge verloren und werden gezählt. Die Anwendung bleibt schnell.
- `blockieren`: Ist die Queue voll, wartet der Aufrufer auf einen Platz und hält seinen HTTP-Thread. Die HTTP-Threads laufen voll, auch die fachlichen Requests werden langsam.

Nach der Flut holt der Schreiber den Rückstand auf.""",
        "warum": """Das Logging läuft über die Applikationsserver: Einträge kommen per HTTP, landen in einer Queue und werden von einem eigenen Thread in eine Datei geschrieben. Kommt mehr an, als der Schreiber wegschafft, wächst der Rückstand um die Differenz – hier 300 Einträge pro Sekunde, bei 8 KB also rund 2,4 MB pro Sekunde.

Es gibt nur drei Möglichkeiten, damit umzugehen, und jede hat einen Preis: Speicher (`unbegrenzt`), Vollständigkeit (`verwerfen`) oder Durchsatz (`blockieren`). Bei `blockieren` teilt sich das Logging die HTTP-Threads mit den fachlichen Requests – eine Log-Flut wird zum Ausfall der Anwendung.

Typische Auslöser sind ein versehentlich aktiviertes Debug-Logging, eine Fehlerkaskade mit Stacktraces oder eine langsame Platte.""",
        "verhindern": """- Die Queue begrenzen und bewusst entscheiden, was bei voller Queue geschieht. Für Logeinträge ist Verwerfen mit Zähler meist richtig: Die Anwendung ist wichtiger als ihr Protokoll.
- Monitoring: Queue-Tiefe, Verzug und verworfene Einträge (`mes_log_*`). Der Verzug ist der früheste Hinweis.
- Logging von der fachlichen Last trennen: eigener Connector oder eigener Executor mit kleiner Thread-Zahl, damit eine Log-Flut nicht alle HTTP-Threads belegt.
- An der Quelle begrenzen: Log-Level in Produktion festlegen, wiederholte gleiche Meldungen zusammenfassen, Größe je Eintrag begrenzen.
- Den Anteil kennen: 3 von 7 Mio. Requests am Tag sind Logeinträge. Ob sie über die Applikationsserver laufen müssen, ist eine Architekturfrage.""",
    },
    "S18": {
        "passiert": """Ein Codepfad holt alle 10 s fünf Connections aus `MES_Connection` und gibt sie nicht zurück. `Active` steigt stufenweise – ohne dass die Last steigt. Das Alter der ältesten ausgeliehenen Connection wächst stetig. Oracle zeigt diese Sessions als inaktiv: Sie führen kein Statement aus, sie warten auf den Client. Ist der Pool bei 50/50, scheitern die normalen Lesezugriffe nach 30 s mit `PoolErschoepft`. Der Zustand bleibt, auch wenn keine Last mehr anliegt.""",
        "warum": """Eine Connection, die nicht geschlossen wird, kehrt nicht in den Pool zurück. Der Pool kann das nicht von einer Connection unterscheiden, die noch gebraucht wird.

Der Unterschied zu S02 liegt in der Sicht der Datenbank: Dort sind die Sessions aktiv, weil langsame Abfragen laufen. Hier sind sie inaktiv, weil niemand mehr etwas mit ihnen tut. Pool voll und Datenbank untätig ist die Signatur eines Lecks.

Zurückholen kann der Pool nur mit `removeAbandoned`. Bei Zollner steht `MES_Connection` auf `removeAbandoned = true` mit 3600 s – das Leck bleibt eine Stunde. `Master_MES_Connection` steht auf `removeAbandoned = false`, der Timeout von 1800 s wirkt dort nicht – das Leck bleibt bis zum Neustart.""",
        "verhindern": """- Im Code: `try-with-resources` für jede Connection, jedes Statement und jedes ResultSet. Das ist die eigentliche Behebung.
- `tomee.xml`: `suspectTimeout = 60` und `logAbandoned = true` – der Pool meldet Connections, die länger als 60 s gehalten werden, mit dem Stacktrace der Stelle, die sie geholt hat.
- `tomee.xml`: `removeAbandoned = true` bei beiden DataSources, `removeAbandonedTimeout` 3600 s → 600 s.
- `tomee.xml`: `jdbcInterceptors` mit `ResetAbandonedTimer` – Aktivität setzt den Timer zurück, lange aktive Batch-Connections werden nicht abgeräumt.
- `tomee.xml`: `timeBetweenEvictionRunsMillis = 30000` mit dem nativen Namen setzen. `timeBetweenEvictionRuns = -1` übernimmt TomEE nicht.
- Monitoring: Alter der ältesten ausgeliehenen Connection (Alarm `ConnectionLangeGehalten`) und `Active` im Leerlauf. Ein Pool, der ohne Last nicht auf 0 zurückgeht, hat ein Leck.""",
    },
    "S19": {
        "passiert": """Auf dem Core (`-Xmx1024m`) bleiben 600 MB Heap dauerhaft belegt, dazu erzeugen 40 Requests pro Sekunde je 512 KB kurzlebigen Müll. Die Old Generation ist fast voll. Der Heap nach der GC bleibt oben, der Anteil der Zeit in der GC steigt auf zweistellige Prozent. Die Antwortzeiten der normalen Lesezugriffe springen – sie haben mit dem Leck nichts zu tun. Die CPU ist hoch, der Durchsatz sinkt. Wächst das Leck weiter, folgt ein `OutOfMemoryError`. Nach der Freigabe ist der Heap mit der nächsten vollen GC wieder leer.""",
        "warum": """Die GC kann nur freigeben, was nicht mehr referenziert wird. Ist die Old Generation dauerhaft fast voll, findet jede Sammlung wenig und läuft entsprechend oft. Während einer Sammlung steht die Anwendung – jede Pause verlängert alle Requests, die gerade laufen.

Der Heap-Füllstand allein sagt wenig: Ein Heap bei 90 % kann gesund sein, wenn die nächste GC ihn auf 30 % bringt. Aussagekräftig sind der Füllstand nach der GC und der Zeitanteil der GC. Steigt der Wert nach der GC über Stunden oder Tage, ist es ein Leck. Ist er stabil hoch, ist der Heap zu klein.""",
        "verhindern": """- Monitoring: Zeitanteil der GC (Alarm `GcZeitanteilHoch` ab 5 %) und Heap nach der GC als Trend. `HeapAuslastungHoch` allein löst auch bei gesundem Sägezahn aus.
- `JAVA_OPTS`: GC-Log aktivieren (`-Xlog:gc*:file=…`) – der einzige Nachweis im Nachhinein.
- `JAVA_OPTS`: `-XX:+HeapDumpOnOutOfMemoryError` mit `-XX:HeapDumpPath` auf ein Verzeichnis mit genug Platz. Der Dump zeigt, was den Heap hält.
- Heap vergrößern hilft nur, wenn es kein Leck ist – und nur innerhalb des Container-Limits (S09, S14).
- Häufige Ursachen im Code: Caches ohne Obergrenze, statische Sammlungen, HTTP-Sessions (S08), unbegrenzte Queues (S17).""",
    },
}
