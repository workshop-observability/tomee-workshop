// Dünne Hülle um die REST-API von server.py

// Adresse der API, aus der Adresse dieser Seite abgeleitet:
//   http://<host>:8070/           → http://<host>:8070/api/…
//   http://<host>:8080/frontend/  → http://<host>:8080/frontend/api/…  (Portal)
// So funktioniert die Oberfläche unter beiden Eingängen, ohne den Pfad zu kennen.
const BASIS = new URL('.', document.baseURI)

async function anfrage(pfad, optionen = {}) {
  const antwort = await fetch(new URL(`api${pfad}`, BASIS), {
    headers: { 'Content-Type': 'application/json' },
    ...optionen,
  })
  const daten = await antwort.json().catch(() => ({}))
  if (!antwort.ok) throw new Error(daten.fehler || `HTTP ${antwort.status}`)
  return daten
}

export const api = {
  info: () => anfrage('/info'),
  katalog: () => anfrage('/szenarien'),
  status: () => anfrage('/status'),
  laeufe: () => anfrage('/laeufe'),
  ausgabe: (nummer, ab) => anfrage(`/laeufe/${nummer}?ab=${ab}`),
  starten: (daten) => anfrage('/laeufe', { method: 'POST', body: JSON.stringify(daten) }),
  // laufend: stoppen, beendet: entfernen
  stoppen: (nummer) => anfrage(`/laeufe/${nummer}`, { method: 'DELETE' }),
}

// Eingaben je Szenario im Browser merken (nur Komfort – fehlt der Speicher, gelten die Standardwerte)
export const gemerkt = {
  lesen(schluessel) {
    try {
      return JSON.parse(localStorage.getItem(`laststeuerung:${schluessel}`) || 'null')
    } catch {
      return null
    }
  },
  schreiben(schluessel, wert) {
    try {
      localStorage.setItem(`laststeuerung:${schluessel}`, JSON.stringify(wert))
    } catch {
      /* privater Modus o. Ä. */
    }
  },
}
