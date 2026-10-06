# syntax=docker/dockerfile:1
#
# ActiveMQ Classic als Broker der Demo – beim Kunden die Container active_mq /
# ha_active_mq (Ports 5672 AMQP, 61613 STOMP, 61614 WebSocket). Dieselbe
# Client-Version wie in TomEE Plume 10.1.2 (activemq-client 6.1.7).
# Dazu der JMX Exporter als Java-Agent: Queue-Tiefe, Konsumenten und Durchsatz
# stehen nur im Broker, nicht in TomEE.

FROM apache/activemq-classic:6.1.7

ADD --chmod=644 https://repo1.maven.org/maven2/io/prometheus/jmx/jmx_prometheus_javaagent/1.0.1/jmx_prometheus_javaagent-1.0.1.jar \
    /opt/jmx_exporter/jmx_prometheus_javaagent.jar
COPY activemq/jmx-exporter.yaml /opt/jmx_exporter/config.yaml
