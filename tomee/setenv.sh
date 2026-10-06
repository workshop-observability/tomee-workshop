#!/bin/sh
# Wird von catalina.sh eingelesen.
# JAVA_OPTS kommt wie beim Kunden aus dem Container-Start (docker-compose.yml).
# Hier kommen nur die Ergänzungen der Demo dazu.

# JMX Exporter als Java-Agent: http://<container>:8888/metrics
CATALINA_OPTS="$CATALINA_OPTS -javaagent:/opt/jmx_exporter/jmx_prometheus_javaagent.jar=8888:/opt/jmx_exporter/config.yaml"

# Threads für alle EJB-Timer der JVM (TomEE-Default: 3)
if [ -n "$TIMER_POOL_SIZE" ]; then
  CATALINA_OPTS="$CATALINA_OPTS -Dopenejb.timer.pool.size=$TIMER_POOL_SIZE"
fi

# JMS: Ohne Konfiguration startet TomEE in jeder JVM einen eigenen, eingebetteten
# Broker ("Default JMS Resource Adapter", BrokerXmlConfig broker:(tcp://localhost:61616)).
# Die Demo lenkt den Default-Adapter auf den ActiveMQ-Container um – über
# conf/system.properties, weil die Resource-ID Leerzeichen enthält. Die tomee.xml des
# Kunden enthält dazu nichts (offene Frage: wo steht es beim Kunden?).
if [ -n "$MES_JMS_URL" ]; then
  SYSPROPS="$CATALINA_BASE/conf/system.properties"
  sed -i '/^# >>> MES-Demo JMS/,/^# <<< MES-Demo JMS/d' "$SYSPROPS"
  cat >> "$SYSPROPS" <<EOF
# >>> MES-Demo JMS (setzt tomee/setenv.sh bei jedem Start)
Default\ JMS\ Resource\ Adapter.BrokerXmlConfig =
Default\ JMS\ Resource\ Adapter.ServerUrl = $MES_JMS_URL
Default\ JMS\ Resource\ Adapter.DataSource =
# <<< MES-Demo JMS
EOF
fi

# Nur der Core holt Nachrichten aus der Queue; auf den anderen Rollen ist die
# Message-Driven Bean deployt, aber nicht aktiv (TomEE-Aktivierungsparameter).
if [ "$MES_JMS_KONSUMENT" != "true" ]; then
  CATALINA_OPTS="$CATALINA_OPTS -DNachrichtenVerarbeitung.activation.MdbActiveOnStartup=false"
fi

# Zusätzliche Optionen je Konfigurationsvariante (z. B. GC-Log, Heap-Dump bei OOM)
CATALINA_OPTS="$CATALINA_OPTS $JAVA_OPTS_EXTRA"

export CATALINA_OPTS
