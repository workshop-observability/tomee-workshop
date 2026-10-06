# Laststeuerung: Vue-Oberfläche + server.py, startet mes_last.py-Läufe.
# Build-Kontext ist lasttest/ (damit mes_last.py mit ins Image kommt):
#   docker compose build laststeuerung

# ─── Stufe 1: Vue-Oberfläche bauen ─────────────────────────────────────────
FROM node:22-alpine AS oberflaeche
WORKDIR /bau
COPY steuerung/frontend/package.json steuerung/frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY steuerung/frontend/ ./
RUN npm run build

# ─── Stufe 2: Laufzeit (nur Python-Standardbibliothek) ─────────────────────
FROM python:3.13-slim
WORKDIR /app
COPY mes_last.py erklaerungen.py steuerung/server.py ./
COPY --from=oberflaeche /bau/dist ./static
ENV MES_HOST=localhost \
    STEUERUNG_PORT=8070 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
EXPOSE 8070
# server.py fängt SIGTERM ab und stoppt laufende Szenarien mit SIGINT (Aufräumen wie bei Strg+C)
CMD ["python3", "server.py"]
