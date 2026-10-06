<script setup>
import { computed, onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import { api, gemerkt } from './api.js'
import { fehlerVon } from './parameterPruefung.js'
import SzenarioListe from './components/SzenarioListe.vue'
import ParameterFormular from './components/ParameterFormular.vue'
import LaufAnsicht from './components/LaufAnsicht.vue'
import StatusLeiste from './components/StatusLeiste.vue'
import ErklaerungKlappe from './components/ErklaerungKlappe.vue'

const info = ref(null)
const katalog = ref({ szenarien: [], kommandos: [] })
const auswahl = ref('S02')
const werte = reactive({}) // Schlüssel (S02 / cmd:last) → { name: wert }
const laeufe = ref([])
const ausgaben = reactive({}) // Laufnummer → { zeilen, naechste }
const gewaehlterLauf = ref(null)
const meldung = ref('')
const startet = ref(false)
const jetzt = ref(Date.now())

// Links auf die übrigen Demo-Dienste:
//   direkt unter :8070         → gleicher Host, Einzelport des Dienstes
//   über das Portal /frontend/ → Nachbarpfad im Portal, relativ gebildet. Schema, Host
//                                und Port der Seite bleiben so erhalten – nötig hinter
//                                einem Reverse Proxy, der nur das Portal durchreicht.
const vm = window.location.hostname
const basis = new URL('.', document.baseURI)
const imPortal = basis.pathname.endsWith('/frontend/')
const dienste = [
  ['Grafana', 3000, 'grafana/'],
  ['Prometheus', 9090, 'prometheus/'],
  ['HAProxy-Statistik', 8989, 'haproxy'],
].map(([name, port, pfad]) => [name, imPortal ? new URL(`../${pfad}`, basis).href : `http://${vm}:${port}`])

const eintrag = computed(() => {
  if (auswahl.value?.startsWith('cmd:')) {
    const k = katalog.value.kommandos.find((x) => `cmd:${x.art}` === auswahl.value)
    return k && { art: k.art, id: null, titel: k.titel, text: k.beschreibung, parameter: k.parameter }
  }
  const sz = katalog.value.szenarien.find((x) => x.id === auswahl.value)
  return (
    sz && {
      art: 'szenario',
      id: sz.id,
      titel: sz.titel,
      modul: sz.modul,
      text: sz.beobachten,
      voraussetzung: sz.voraussetzung,
      erklaerung: sz.erklaerung,
      parameter: sz.parameter,
    }
  )
})

const aktuelleWerte = computed(() => werte[auswahl.value] || {})

const hatFehler = computed(() =>
  (eintrag.value?.parameter || []).some((p) => fehlerVon(p, aktuelleWerte.value[p.name])),
)

const aktiveSchluessel = computed(
  () => new Set(laeufe.value.filter((l) => l.laeuft).map((l) => (l.art === 'szenario' ? l.id : `cmd:${l.art}`))),
)

const vorschau = computed(() => {
  const e = eintrag.value
  if (!e || e.art !== 'szenario') return ''
  const abweichend = e.parameter
    .filter((p) => aktuelleWerte.value[p.name] !== p.standard && aktuelleWerte.value[p.name] !== '')
    .map((p) => ` -p ${p.name}=${aktuelleWerte.value[p.name]}`)
    .join('')
  return `python3 lasttest/mes_last.py --host ${vm} szenario ${e.id}${abweichend}`
})

const lauf = computed(() => laeufe.value.find((l) => l.nummer === gewaehlterLauf.value))

function standardwerte(parameter) {
  return Object.fromEntries(parameter.map((p) => [p.name, p.standard]))
}

function werteVorbereiten() {
  const alle = [
    ...katalog.value.szenarien.map((s) => [s.id, s.parameter]),
    ...katalog.value.kommandos.map((k) => [`cmd:${k.art}`, k.parameter]),
  ]
  for (const [schluessel, parameter] of alle) {
    const basis = standardwerte(parameter)
    const alt = gemerkt.lesen(`werte:${schluessel}`) || {}
    // nur gemerkte Werte übernehmen, die es (noch) gibt
    for (const name of Object.keys(basis)) if (name in alt) basis[name] = alt[name]
    werte[schluessel] = basis
  }
}

function aendern(neu) {
  werte[auswahl.value] = neu
  gemerkt.schreiben(`werte:${auswahl.value}`, neu)
}

function zuruecksetzen() {
  aendern(standardwerte(eintrag.value.parameter))
}

function waehlen(schluessel) {
  auswahl.value = schluessel
  gemerkt.schreiben('auswahl', schluessel)
}

async function starten() {
  const e = eintrag.value
  startet.value = true
  meldung.value = ''
  try {
    const parameter = Object.fromEntries(Object.entries(aktuelleWerte.value).filter(([, w]) => w !== ''))
    const neu = await api.starten({ art: e.art, id: e.id, parameter })
    laeufe.value = [neu, ...laeufe.value]
    gewaehlterLauf.value = neu.nummer
  } catch (err) {
    meldung.value = `Start abgelehnt: ${err.message}`
  } finally {
    startet.value = false
  }
}

async function stoppen(nummer) {
  try {
    await api.stoppen(nummer)
    await laeufeLaden()
  } catch (err) {
    meldung.value = err.message
  }
}

async function entfernen(nummer) {
  await stoppen(nummer)
  delete ausgaben[nummer]
  if (gewaehlterLauf.value === nummer) gewaehlterLauf.value = laeufe.value[0]?.nummer ?? null
}

async function laeufeLaden() {
  laeufe.value = await api.laeufe()
  if (gewaehlterLauf.value === null && laeufe.value.length) gewaehlterLauf.value = laeufe.value[0].nummer
}

async function ausgabeLaden() {
  const l = lauf.value
  if (!l) return
  if (!ausgaben[l.nummer]) ausgaben[l.nummer] = { zeilen: [], naechste: 0 }
  const puffer = ausgaben[l.nummer] // reaktiver Proxy, nicht das rohe Objekt
  // beendete Läufe nur einmal vollständig nachladen
  if (!l.laeuft && puffer.fertig) return
  const antwort = await api.ausgabe(l.nummer, puffer.naechste)
  puffer.zeilen.push(...antwort.zeilen)
  if (puffer.zeilen.length > 20000) puffer.zeilen.splice(0, puffer.zeilen.length - 20000)
  puffer.naechste = antwort.naechste
  puffer.fertig = !antwort.lauf.laeuft
  const i = laeufe.value.findIndex((x) => x.nummer === l.nummer)
  if (i >= 0) laeufe.value[i] = antwort.lauf
}

let tick = 0
let timer = null
async function takt() {
  jetzt.value = Date.now()
  try {
    if (tick++ % 3 === 0) await laeufeLaden()
    await ausgabeLaden()
  } catch {
    /* Server kurz nicht erreichbar – nächster Takt versucht es erneut */
  }
}

onMounted(async () => {
  try {
    ;[info.value, katalog.value] = await Promise.all([api.info(), api.katalog()])
    werteVorbereiten()
    const alt = gemerkt.lesen('auswahl')
    if (alt && werte[alt]) auswahl.value = alt
    await laeufeLaden()
  } catch (err) {
    meldung.value = `Laststeuerung nicht erreichbar: ${err.message}`
  }
  timer = setInterval(takt, 1000)
})
onBeforeUnmount(() => clearInterval(timer))

function punktKlasse(l) {
  if (l.zustand === 'räumt auf') return 'raeumt'
  if (l.laeuft) return 'laeuft'
  return l.zustand === 'Fehler' ? 'fehler' : 'aus'
}
</script>

<template>
  <header class="kopfleiste">
    <div class="marke">
      <strong>MES-Demo · Laststeuerung</strong>
      <span v-if="info" class="ziel">Ziel: <code>{{ info.host }}</code></span>
    </div>
    <nav class="dienste">
      <a v-for="[name, adresse] in dienste" :key="name" :href="adresse" target="_blank" rel="noopener">
        {{ name }}
      </a>
    </nav>
  </header>

  <p v-if="meldung" class="meldung" @click="meldung = ''">{{ meldung }} <span class="schliessen">×</span></p>

  <div class="layout">
    <aside class="karte seitenleiste">
      <SzenarioListe
        :szenarien="katalog.szenarien"
        :kommandos="katalog.kommandos"
        :auswahl="auswahl"
        :aktiv="aktiveSchluessel"
        @waehlen="waehlen"
      />
    </aside>

    <main class="inhalt">
      <section v-if="eintrag" class="karte detail">
        <div class="detail-kopf">
          <div>
            <span v-if="eintrag.modul" class="modul">{{ eintrag.modul }}</span>
            <h1>
              <span v-if="eintrag.id" class="kennung">{{ eintrag.id }}</span>
              {{ eintrag.titel }}
            </h1>
          </div>
          <button v-if="eintrag.parameter.length" @click="zuruecksetzen">Standardwerte</button>
        </div>

        <p class="beobachten">
          <span v-if="eintrag.art === 'szenario'" class="etikett">Beobachten</span>
          {{ eintrag.text }}
        </p>
        <p v-if="eintrag.voraussetzung" class="voraussetzung">⚠ {{ eintrag.voraussetzung }}</p>

        <ParameterFormular :parameter="eintrag.parameter" :werte="aktuelleWerte" @aendern="aendern" />

        <div class="startzeile">
          <code v-if="vorschau" class="vorschau" title="Gleiches Szenario auf der Kommandozeile">{{ vorschau }}</code>
          <span v-else />
          <button class="primaer" :disabled="startet || hatFehler" @click="starten">
            {{ eintrag.art === 'reset' ? 'Zurücknehmen' : 'Starten' }}
          </button>
        </div>
        <p v-if="aktiveSchluessel.has(auswahl)" class="warnung">
          Dieser Lauf ist bereits aktiv. Ein zweiter Start überlagert die Last und das Aufräumen.
        </p>

        <ErklaerungKlappe v-if="eintrag.erklaerung" :key="eintrag.id" :erklaerung="eintrag.erklaerung" />
      </section>

      <StatusLeiste />

      <section class="karte laeufe">
        <div class="lauf-reiter">
          <h2>Läufe</h2>
          <button
            v-for="l in laeufe"
            :key="l.nummer"
            class="reiter"
            :class="{ gewaehlt: l.nummer === gewaehlterLauf }"
            @click="gewaehlterLauf = l.nummer"
          >
            <span class="punkt" :class="punktKlasse(l)" />
            #{{ l.nummer }} {{ l.id || l.art }}
          </button>
          <span v-if="!laeufe.length" class="leer">Noch nichts gestartet.</span>
        </div>
        <LaufAnsicht
          v-if="lauf"
          :key="lauf.nummer"
          :lauf="lauf"
          :zeilen="ausgaben[lauf.nummer]?.zeilen || []"
          :jetzt="jetzt"
          @stoppen="stoppen(lauf.nummer)"
          @entfernen="entfernen(lauf.nummer)"
        />
      </section>
    </main>
  </div>
</template>

<style scoped>
.kopfleiste {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  flex-wrap: wrap;
  padding: 10px 20px;
  background: var(--flaeche);
  border-bottom: 1px solid var(--rand);
}

.marke {
  display: flex;
  align-items: baseline;
  gap: 14px;
  flex-wrap: wrap;
}

.ziel {
  color: var(--text-2);
  font-size: 13px;
}

.dienste {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
  font-size: 13px;
}

.meldung {
  margin: 12px 20px 0;
  padding: 8px 12px;
  border-radius: 6px;
  background: color-mix(in srgb, var(--schlecht) 12%, var(--flaeche));
  border: 1px solid color-mix(in srgb, var(--schlecht) 40%, transparent);
  cursor: pointer;
}

.schliessen {
  float: right;
  color: var(--text-2);
}

.layout {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 16px;
  padding: 16px 20px 24px;
  align-items: start;
}

.seitenleiste {
  padding: 10px;
  position: sticky;
  top: 16px;
  max-height: calc(100vh - 32px);
  overflow-y: auto;
}

.inhalt {
  display: flex;
  flex-direction: column;
  gap: 16px;
  min-width: 0;
}

.detail {
  padding: 16px 18px;
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.detail-kopf {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
}

.modul {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-2);
}

h1 {
  margin: 2px 0 0;
  font-size: 19px;
  line-height: 1.3;
}

h1 .kennung {
  font-family: var(--mono);
  color: var(--akzent);
  margin-right: 6px;
}

.beobachten {
  margin: 0;
}

.etikett {
  display: inline-block;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--akzent);
  margin-right: 6px;
}

.voraussetzung,
.warnung {
  margin: 0;
  padding: 8px 12px;
  border-radius: 6px;
  background: var(--hinweis-bg);
  border: 1px solid var(--hinweis-rand);
}

.startzeile {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding-top: 12px;
  border-top: 1px solid var(--rand);
}

.vorschau {
  color: var(--text-2);
  overflow-x: auto;
  white-space: nowrap;
  min-width: 0;
}

.startzeile .primaer {
  flex: none;
  min-width: 120px;
}

.laeufe {
  padding: 12px 14px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.lauf-reiter {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.lauf-reiter h2 {
  margin: 0 8px 0 0;
  font-size: 14px;
}

.reiter {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 3px 10px;
  font-size: 12.5px;
  font-family: var(--mono);
}

.reiter.gewaehlt {
  border-color: var(--akzent);
  background: color-mix(in srgb, var(--akzent) 10%, var(--flaeche));
}

.leer {
  color: var(--text-2);
}

@media (max-width: 900px) {
  .layout {
    grid-template-columns: minmax(0, 1fr);
    padding: 12px 16px 20px;
  }

  .seitenleiste {
    position: static;
    max-height: 320px;
  }

  .startzeile {
    flex-direction: column;
    align-items: stretch;
  }
}
</style>
