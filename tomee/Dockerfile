# syntax=docker/dockerfile:1
#
# TomEE-Image der Demo. Nachbildung des Kundenaufbaus:
# Rocky Linux im Container, TomEE Plume 10.1.2 unter /opt/apache-tomee-plume-10.1.2,
# Oracle-JDBC-Treiber in tomee/lib, JMX Exporter als Java-Agent.
# Build-Kontext ist code-demo/ (siehe docker-compose.yml).

# ─── Stufe 1: Anwendung bauen, Artefakte von Maven Central holen ─────────────
FROM maven:3.9-eclipse-temurin-21 AS bau
WORKDIR /bau
COPY mes-demo-app/pom.xml .
RUN --mount=type=cache,target=/root/.m2 mvn -B -q dependency:go-offline || true
COPY mes-demo-app/src src
RUN --mount=type=cache,target=/root/.m2 set -e; \
    mvn -B -q package; \
    for a in org.apache.tomee:apache-tomee:10.1.2:tar.gz:plume \
             com.oracle.database.jdbc:ojdbc11:23.26.3.0.0 \
             io.prometheus.jmx:jmx_prometheus_javaagent:1.0.1; do \
      mvn -B -q org.apache.maven.plugins:maven-dependency-plugin:3.8.1:copy \
          -Dartifact="$a" -DoutputDirectory=/artefakte; \
    done

# ─── Stufe 2: Laufzeit ───────────────────────────────────────────────────────
FROM rockylinux/rockylinux:9-minimal

RUN microdnf -y install java-21-openjdk-headless procps-ng tar gzip findutils iproute \
 && microdnf clean all

ENV CATALINA_HOME=/opt/apache-tomee-plume-10.1.2 \
    CATALINA_BASE=/opt/apache-tomee-plume-10.1.2 \
    TZ=Europe/Berlin

COPY --from=bau /artefakte/apache-tomee-10.1.2-plume.tar.gz /tmp/
RUN tar xzf /tmp/apache-tomee-10.1.2-plume.tar.gz -C /opt \
 && rm /tmp/apache-tomee-10.1.2-plume.tar.gz \
 && rm -rf "$CATALINA_HOME"/webapps/* \
 && mkdir -p /opt/jmx_exporter /mnt/mes_data

COPY --from=bau /artefakte/ojdbc11-23.26.3.0.0.jar $CATALINA_HOME/lib/
COPY --from=bau /artefakte/jmx_prometheus_javaagent-1.0.1.jar /opt/jmx_exporter/jmx_prometheus_javaagent.jar
COPY tomee/jmx-exporter.yaml /opt/jmx_exporter/config.yaml
COPY tomee/setenv.sh $CATALINA_HOME/bin/setenv.sh
RUN chmod +x $CATALINA_HOME/bin/*.sh

# tomee.xml und server.xml kommen per Volume aus tomee/konfig/<KONFIG>/
COPY --from=bau /bau/target/mes.war $CATALINA_HOME/webapps/mes.war

WORKDIR $CATALINA_HOME
EXPOSE 8080 8888
CMD ["/opt/apache-tomee-plume-10.1.2/bin/catalina.sh", "run"]
