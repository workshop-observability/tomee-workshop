#!/usr/bin/env bash
# Zugang zur Demo, wenn die Firewall der Cloud nicht änderbar ist (z. B. Azure-VM
# im Konto eines Kollegen: nur SSH kommt durch, sonst nichts).
#
#   ./zugang.sh tunnel [adresse]    SSH-Tunnel-Befehl für den eigenen Rechner
#
# SSH leitet damit alle Demo-Ports auf den eigenen Rechner weiter; die Demo ist
# dann unter localhost erreichbar – auch JConsole und Oracle, die kein HTTP sind.
# Eine Freigabe in der Cloud braucht es dafür nicht.
#
# Ob ein anderer Port doch offen ist, misst man vom eigenen Rechner aus, ohne
# hier etwas zu starten (-Pn, weil Azure ICMP verwirft und nmap sonst aufgibt):
#
#   nmap -Pn -p 80,443,3000,8070,8080,9090 <adresse>
#
#   open      – offen, dort könnte die Demo hinter einem Proxy liegen
#   closed    – die Firewall lässt durch, es hört nur niemand (ebenso brauchbar)
#   filtered  – von der Cloud verworfen, der Port ist zu
#
# Ohne nmap, ein Port je Durchlauf (ncat nimmt nicht mehrere auf einmal):
#
#   for p in 80 443 3000 8070 8080; do nc -zvw3 <adresse> $p; done
#
# Kommt genau ein Port durch, reicht das Portal: unter :8080 liegen alle
# Weboberflächen (/grafana/, /prometheus/, /frontend/ …). Nur JConsole und
# Oracle brauchen weiterhin eigene Ports oder den Tunnel.
set -euo pipefail

cd "$(dirname "$(readlink -f "$0")")"

# dieselbe Portliste wie in start.sh
eval "$(grep '^PORTS=' start.sh)"

adresse() {
  # Adresse aus .env, sonst Platzhalter – die VM kennt ihre öffentliche IP nicht
  local a
  a=$(grep "^REMOTE_HOST=" .env 2> /dev/null | cut -d= -f2) || true
  echo "${1:-${a:-<öffentliche-adresse>}}"
}

tunnel() {
  local ziel=$1 nutzer=${SUDO_USER:-$USER} weiterleitungen="" p von bis
  for p in $PORTS; do
    case "$p" in
      *-*) von=${p%-*}; bis=${p#*-} ;;
      *)   von=$p; bis=$p ;;
    esac
    for ((n = von; n <= bis; n++)); do
      weiterleitungen+=" -L $n:localhost:$n"
    done
  done

  cat <<EOF

SSH-Tunnel: auf dem EIGENEN Rechner starten und offen lassen.

  ssh$weiterleitungen \\
      $nutzer@$ziel

Danach läuft alles über localhost, als liefe die Demo auf dem eigenen Rechner:

  Portal         http://localhost:8080        (alle Oberflächen unter einer Adresse)
  Grafana        http://localhost:3000        Laststeuerung  http://localhost:8070
  Prometheus     http://localhost:9090        HAProxy        http://localhost:8989
  Core           http://localhost:8200/mes/api/status
  Oracle         localhost:1521/FREEPDB1

Für JConsole muss die Demo sich als localhost melden, sonst schickt RMI den
Client auf eine Adresse, die er nicht erreicht. Einmalig auf der VM:

  ./start.sh --host 127.0.0.1

Dann verbindet  jconsole localhost:9200  durch den Tunnel.

Teilnehmer ohne SSH-Zugang kommen so nicht dran – für die braucht es einen
offenen Port oder einen ausgehenden Tunneldienst.
EOF
}

case "${1:-}" in
  tunnel) shift; tunnel "$(adresse "${1:-}")" ;;
  *) echo "Aufruf: ./zugang.sh tunnel [adresse]" >&2; exit 1 ;;
esac
