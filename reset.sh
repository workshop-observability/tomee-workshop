#!/usr/bin/env bash
# Entfernt alles, was start.sh angelegt hat. Der nächste ./start.sh beginnt
# danach mit einer komplett frischen Umgebung.
#
#   ./loeschen.sh
#
# Entfernt werden
#   - alle Container, Netzwerke und Volumes der Demo (Oracle-Daten, Metriken, Logs),
#   - die selbst gebauten Images mes-demo-tomee und mes-demo-laststeuerung,
#   - der systemd-Dienst mes-demo (kein Autostart mehr),
#   - die Firewall-Freigaben der Demo-Ports,
#   - .env – sie wird als .env.bak aufbewahrt; start.sh legt eine neue aus .env.example an.
#
# Docker selbst bleibt installiert.
set -euo pipefail

# Docker, Firewall und systemd brauchen root
[ "$(id -u)" -eq 0 ] || exec sudo "$0" "$@"
cd "$(dirname "$(readlink -f "$0")")"

# dieselbe Portliste wie in start.sh
eval "$(grep '^PORTS=' start.sh)"

read -r -p "Demo-Umgebung mit allen Daten löschen? [j/N] " antwort
[ "$antwort" = j ] || exit 0

echo ">> Container, Volumes und Images"
if command -v docker > /dev/null; then
  docker compose --profile facade down --volumes --remove-orphans
  # mes-demo-activemq: nur noch für ältere Installationen
  docker image rm -f mes-demo-tomee:latest mes-demo-laststeuerung:latest mes-demo-activemq:latest > /dev/null 2>&1 || true
fi

echo ">> Autostart"
if [ -f /etc/systemd/system/mes-demo.service ]; then
  systemctl -q disable mes-demo.service
  rm /etc/systemd/system/mes-demo.service
  systemctl daemon-reload
fi

echo ">> Firewall"
if systemctl -q is-active firewalld; then
  for p in $PORTS; do
    firewall-cmd -q --remove-port="$p/tcp"
    firewall-cmd -q --permanent --remove-port="$p/tcp"
  done
elif command -v ufw > /dev/null && ufw status | grep -q "Status: active"; then
  for p in $PORTS; do
    ufw delete allow "${p/-/:}/tcp" > /dev/null || true
  done
fi

echo ">> Einstellungen"
if [ -f .env ]; then
  mv .env .env.bak
  echo "   .env → .env.bak"
fi

echo
echo "Fertig. Neu starten mit: ./start.sh"
