#!/usr/bin/env bash
# Richtet die MES-Demo auf diesem Server ein und startet sie.
#
#   ./start.sh                  mit den Einstellungen aus .env (so auch beim Autostart)
#   ./start.sh optimiert        Tuning-Variante
#   ./start.sh kunde            Kundenkonfiguration
#   ./start.sh kunde --facade   zusätzlich den Facade-Container (OOM-Szenario S18)
#   ./start.sh --reset          Oracle-Daten und Metriken verwerfen, frisch starten
#   ./start.sh --host 20.0.0.1  Adresse, unter der die Demo von außen erreicht wird
#                               (Cloud-VM hinter NAT: die öffentliche Adresse)
#
# Variante, Facade und Adresse werden in .env gespeichert und gelten auch nach
# einem Reboot.
# Alle anderen Einstellungen (Heap, Pools, Timeouts) in .env ändern, dann ./start.sh.
#
# Bei jedem Aufruf wird sichergestellt, dass
#   - Docker mit Compose installiert ist (Rocky/Alma/RHEL, Fedora, Ubuntu, Debian),
#   - die Demo-Ports in der Firewall (firewalld oder ufw) freigegeben sind,
#   - der systemd-Dienst mes-demo die Demo nach einem Reboot startet.
#
# Stoppen: docker compose --profile facade stop
# Alles entfernen (nächster Start komplett frisch): ./loeschen.sh
set -euo pipefail

# Docker, Firewall und systemd brauchen root
[ "$(id -u)" -eq 0 ] || exec sudo "$0" "$@"
cd "$(dirname "$(readlink -f "$0")")"

PORTS="1521 3000 8070 8080 8085 8090 8095 8100 8200 8300 8400 8881-8884 8989 9090 9100 9200 9300 9400 50000-50004"

# ─── Hilfsfunktionen ─────────────────────────────────────────────────────────

wert() {
  grep "^$1=" .env | cut -d= -f2 || true
}

setze() {
  if grep -q "^$1=" .env; then
    sed -i "s|^$1=.*|$1=$2|" .env
  else
    echo "$1=$2" >> .env
  fi
}

installiere_docker() {
  . /etc/os-release
  case " $ID ${ID_LIKE:-} " in
    *" debian "*)
      apt-get update
      apt-get install -y ca-certificates curl
      install -m 0755 -d /etc/apt/keyrings
      curl -fsSL "https://download.docker.com/linux/$ID/gpg" -o /etc/apt/keyrings/docker.asc
      echo "deb [signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$ID $VERSION_CODENAME stable" \
        > /etc/apt/sources.list.d/docker.list
      apt-get update
      apt-get install -y docker-ce docker-buildx-plugin docker-compose-plugin
      ;;
    *" fedora "*)
      # Fedora und RHEL haben eigene Repos, Rocky/Alma nutzen das CentOS-Repo
      local repo=centos
      case $ID in fedora|rhel) repo=$ID ;; esac
      curl -fsSL "https://download.docker.com/linux/$repo/docker-ce.repo" -o /etc/yum.repos.d/docker-ce.repo
      dnf install -y docker-ce docker-buildx-plugin docker-compose-plugin
      ;;
    *)
      echo "Docker bitte manuell installieren – $PRETTY_NAME wird nicht unterstützt." >&2
      exit 1
      ;;
  esac
}

gib_ports_frei() {
  if systemctl -q is-active firewalld; then
    # sofort und dauerhaft, ohne Reload (der würde laufende Docker-Regeln stören)
    for p in $PORTS; do
      firewall-cmd -q --add-port="$p/tcp"
      firewall-cmd -q --permanent --add-port="$p/tcp"
    done
  elif command -v ufw > /dev/null && ufw status | grep -q "Status: active"; then
    for p in $PORTS; do
      ufw allow "${p/-/:}/tcp" > /dev/null
    done
  fi
}

richte_autostart_ein() {
  local datei=/etc/systemd/system/mes-demo.service
  # Aufruf über bash: SELinux erlaubt systemd nicht, Skripte im Home direkt auszuführen
  local inhalt="[Unit]
Description=MES-Demo (Workshop Monitorability & Performance Tuning)
Requires=docker.service
After=docker.service network-online.target
Wants=network-online.target

[Service]
ExecStart=/bin/bash $(pwd)/start.sh

[Install]
WantedBy=multi-user.target"

  if [ "$(cat "$datei" 2> /dev/null)" != "$inhalt" ]; then
    echo "$inhalt" > "$datei"
    systemctl daemon-reload
  fi
  systemctl -q enable mes-demo.service
}

ipv4() {
  [[ ${1:-} =~ ^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+$ ]] && echo "$1" || true
}

# Fragt den Metadatendienst der Cloud (169.254.169.254) nach der öffentlichen
# Adresse dieser VM. Ausgabe: "<Cloud> <IP>". Eine leere IP bei erkannter Cloud
# heißt: Die VM hat keine eigene öffentliche Adresse, sie hängt hinter Load
# Balancer, NAT Gateway oder Bastion – deren Adresse kennt sie nicht.
cloud_adresse() {
  local ip= token=
  # Azure: erst prüfen, ob der Dienst überhaupt antwortet (dann ist es Azure)
  if curl -s -f --connect-timeout 1 --max-time 3 -H Metadata:true \
       "http://169.254.169.254/metadata/instance/compute/location?api-version=2021-02-01&format=text" > /dev/null; then
    ip=$(curl -s --max-time 3 -H Metadata:true \
         "http://169.254.169.254/metadata/instance/network/interface/0/ipv4/ipAddress/0/publicIpAddress?api-version=2021-02-01&format=text") || true
    echo "Azure $(ipv4 "$ip")"
    return
  fi
  # AWS: IMDSv2 verlangt zuerst ein Token
  token=$(curl -s -f --connect-timeout 1 --max-time 3 -X PUT \
          -H "X-aws-ec2-metadata-token-ttl-seconds: 60" \
          http://169.254.169.254/latest/api/token) || true
  if [ -n "$token" ]; then
    ip=$(curl -s -f --max-time 3 -H "X-aws-ec2-metadata-token: $token" \
         http://169.254.169.254/latest/meta-data/public-ipv4) || true
    echo "AWS $(ipv4 "$ip")"
    return
  fi
  # GCP
  if curl -s -f --connect-timeout 1 --max-time 3 -H "Metadata-Flavor: Google" \
       http://metadata.google.internal/computeMetadata/v1/instance/id > /dev/null; then
    ip=$(curl -s -f --max-time 3 -H "Metadata-Flavor: Google" \
         "http://metadata.google.internal/computeMetadata/v1/instance/network-interfaces/0/access-configs/0/external-ip") || true
    echo "GCP $(ipv4 "$ip")"
  fi
}

# ─── Parameter ───────────────────────────────────────────────────────────────

konfig=; facade=; reset=; host=
while [ $# -gt 0 ]; do
  case "$1" in
    kunde|optimiert) konfig=$1 ;;
    --facade) facade=facade ;;
    --reset) reset=1 ;;
    --host) shift; host=${1:-} ;;
    --host=*) host=${1#--host=} ;;
    *) echo "Unbekannter Parameter: $1 (erlaubt: kunde, optimiert, --facade, --reset, --host <adresse>)" >&2; exit 1 ;;
  esac
  shift
done

# ─── Einrichten ──────────────────────────────────────────────────────────────

if [ ! -f .env ]; then
  cp .env.example .env
fi
if [ -n "$konfig" ]; then
  setze KONFIG "$konfig"
fi
# Facade läuft genau dann, wenn beim letzten Wechsel --facade angegeben war
if [ -n "$konfig$facade" ]; then
  setze COMPOSE_PROFILES "$facade"
fi
# --host: die Adresse, unter der die Demo von außen erreicht wird, fest eintragen
if [ -n "$host" ]; then
  setze REMOTE_HOST "$host"
fi
# .env soll dem Benutzer gehören, nicht root
chown --reference=.env.example .env

# Port des Portals; der Standard 8080 steht schon in PORTS
PORTAL_PORT=$(wert PORTAL_PORT)
PORTAL_PORT=${PORTAL_PORT:-8080}
[ "$PORTAL_PORT" = 8080 ] || PORTS="$PORTS $PORTAL_PORT"

command -v docker > /dev/null || installiere_docker
systemctl -q enable --now docker
if [ -n "${SUDO_USER:-}" ]; then
  usermod -aG docker "$SUDO_USER"
fi
gib_ports_frei
richte_autostart_ein

ram_mb=$(awk '/MemTotal/ {print int($2 / 1024)}' /proc/meminfo)
if [ "$ram_mb" -lt 7500 ]; then
  echo "Warnung: nur $ram_mb MB RAM – empfohlen sind 8 GB."
fi

# ─── Starten ─────────────────────────────────────────────────────────────────

# REMOTE_HOST leer = Adresse dieses Servers, bei jedem Start neu ermittelt.
# So passt dieselbe .env auf jeden Server.
#
# In einer Cloud (Azure, AWS, GCP) hat die VM nur die private Adresse ihres
# virtuellen Netzes (z. B. 172.16.0.4). Von außen erreichbar ist sie über eine
# öffentliche Adresse, die per NAT davorhängt und auf keiner Netzwerkkarte der
# VM auftaucht – "hostname -I" findet sie deshalb nicht. Der Metadatendienst der
# Cloud (169.254.169.254, nur von der VM selbst erreichbar) kennt sie.
export REMOTE_HOST=$(wert REMOTE_HOST)
INTERN=$(hostname -I | awk '{print $1}')
CLOUD=; EXTERN=
read -r CLOUD EXTERN <<< "$(cloud_adresse)" || true

if [ -z "$REMOTE_HOST" ]; then
  REMOTE_HOST=${EXTERN:-$INTERN}
fi
KONFIG=$(wert KONFIG)
HOST=$REMOTE_HOST

if [ -n "$reset" ]; then
  docker compose --profile facade down -v
fi
if [ -z "$(wert COMPOSE_PROFILES)" ]; then
  docker rm -f mes-facade > /dev/null 2>&1 || true
fi

echo ">> Konfiguration: $KONFIG, Host: $HOST"
if [ -n "$CLOUD" ]; then
  echo ">> $CLOUD-VM: im virtuellen Netz $INTERN"
fi
docker compose up -d --build

echo ">> Warte auf die Anwendung (Oracle braucht beim ersten Start etwa eine Minute) ..."
for port in 8200 8300 8100; do
  for _ in $(seq 1 60); do
    curl -sf "http://localhost:$port/mes/api/status" > /dev/null && break
    sleep 5
  done
done

cat <<EOF

Demo läuft (Konfiguration: $KONFIG)

  Alles unter einer Adresse:  http://$HOST:$PORTAL_PORT

      /frontend/   Laststeuerung        /core/mes/api/status
      /grafana/    admin / admin        /fileprocessing/mes/api/status
      /prometheus/ Alarme: /alerts      /singleton/mes/api/status
      /haproxy     Statistik            /lb/mes/api/status  (über HAProxy)
      /cadvisor/   Container-Sicht      /metriken/core/metrics

  Dieselben Dienste weiterhin auf ihren eigenen Ports:

  Grafana              http://$HOST:3000            admin / admin
  Prometheus           http://$HOST:9090            Alarme: /alerts
  HAProxy-Statistik    http://$HOST:8989

  Core                 http://$HOST:8200/mes/api/status     JMX $HOST:9200   Metriken :8882/metrics
  FileProcessing       http://$HOST:8300/mes/api/status     JMX $HOST:9300   Metriken :8883/metrics
  Singleton            http://$HOST:8100/mes/api/status     JMX $HOST:9100   Metriken :8881/metrics
  über HAProxy         http://$HOST:8090/mes/api/status

  JConsole:  jconsole $HOST:9200
  Oracle:    $HOST:1521/FREEPDB1   MES_MONITOR / mes_demo

  Last und Szenarien:  http://$HOST:8070   (Weboberfläche, auch $PORTAL_PORT/frontend/)
                       python3 lasttest/mes_last.py --host $HOST hilfe
EOF

if [ -n "$CLOUD" ] && [ "$HOST" = "$INTERN" ]; then
  cat <<EOF
$HOST ist die Adresse im virtuellen Netz – von außen ist die Demo darunter nicht
erreichbar. Die Adresse, über die du dich per SSH verbindest, einmal eintragen:

  ./start.sh --host <öffentliche Adresse>

Sie landet in .env und gilt auch nach einem Reboot. Die Ports müssen zusätzlich
in der Firewall der Cloud freigegeben sein (Azure: Netzwerksicherheitsgruppe).

EOF
elif [ -n "$CLOUD" ]; then
  cat <<EOF
Erreichbar ist das alles nur, solange die Ports in der Firewall der Cloud
freigegeben sind. Sind sie offen, stehen auch JMX
(9100/9200/9300/9400) und Oracle (1521) ohne Anmeldung im Netz: keine echten
Kundendaten einspielen, die VM nach dem Workshop abschalten oder löschen.

EOF
fi
