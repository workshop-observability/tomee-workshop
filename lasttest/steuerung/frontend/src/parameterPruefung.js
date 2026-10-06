// Prüfung im Formular – nur als Hinweis. Verbindlich prüft server.py mit denselben
// Regeln wie die Kommandozeile (Klasse P in mes_last.py).
export function fehlerVon(p, wert) {
  if (p.typ !== 'ganzzahl' && p.typ !== 'zahl') return ''
  if (wert === '' || wert === undefined || wert === null) return 'Wert fehlt'
  if (Number.isNaN(wert)) return 'keine Zahl'
  if (p.typ === 'ganzzahl' && !Number.isInteger(wert)) return 'ganze Zahl erwartet'
  if (p.min !== null && wert < p.min) return `mindestens ${p.min}`
  if (p.max !== null && wert > p.max) return `höchstens ${p.max}`
  return ''
}
