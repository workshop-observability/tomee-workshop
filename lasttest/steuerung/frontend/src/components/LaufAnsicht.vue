<script setup>
import { computed, nextTick, ref, watch } from 'vue'

const props = defineProps({
  lauf: { type: Object, required: true },
  zeilen: { type: Array, required: true },
  jetzt: { type: Number, required: true },
})
const emit = defineEmits(['stoppen', 'entfernen'])

const konsole = ref(null)
const mitlaufen = ref(true)

watch(
  () => props.zeilen.length,
  async () => {
    if (!mitlaufen.value) return
    await nextTick()
    if (konsole.value) konsole.value.scrollTop = konsole.value.scrollHeight
  },
)

function klasse(zeile) {
  if (zeile.startsWith('>>>')) return 'hinweis'
  if (zeile.startsWith('===')) return 'titelzeile'
  if (zeile.startsWith('──')) return 'trenner'
  if (/Fehler|Traceback|nicht erreichbar|HTTP [45]\d\d|TIMEOUT|Abgebrochen/.test(zeile)) return 'fehler'
  return ''
}

function dauer(lauf) {
  const s = Math.max(0, Math.round((lauf.ende ?? props.jetzt / 1000) - lauf.beginn))
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`
}

// server.py kennt nur sein eigenes Ziel (im Container localhost) – für die Anzeige gilt der Host der Oberfläche
const kommando = computed(() => props.lauf.kommando.replace('<vm>', window.location.hostname))

function kopieren() {
  navigator.clipboard?.writeText(kommando.value)
}
</script>

<template>
  <div class="lauf">
    <div class="kopf">
      <div class="titel">
        <strong>#{{ lauf.nummer }} {{ lauf.titel }}</strong>
        <span class="zustand">{{ lauf.zustand }} · {{ dauer(lauf) }}</span>
      </div>
      <div class="aktionen">
        <label class="schalter"><input v-model="mitlaufen" type="checkbox" /> mitlaufen</label>
        <button v-if="lauf.laeuft" class="gefahr" :disabled="lauf.zustand === 'räumt auf'" @click="emit('stoppen')">
          Stoppen (Strg+C)
        </button>
        <button v-else @click="emit('entfernen')">Entfernen</button>
      </div>
    </div>
    <div class="kommando">
      <code>{{ kommando }}</code>
      <button class="klein" title="Kommando kopieren" @click="kopieren">kopieren</button>
    </div>
    <pre ref="konsole" class="konsole"><span
        v-for="(z, i) in zeilen"
        :key="i"
        :class="klasse(z)"
      >{{ z }}
</span><span v-if="!zeilen.length" class="trenner">warte auf Ausgabe …</span></pre>
  </div>
</template>

<style scoped>
.lauf {
  display: flex;
  flex-direction: column;
  gap: 8px;
  min-height: 0;
}

.kopf {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.titel {
  display: flex;
  flex-direction: column;
}

.zustand {
  color: var(--text-2);
  font-size: 12px;
}

.aktionen {
  display: flex;
  align-items: center;
  gap: 10px;
}

.schalter {
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--text-2);
  font-size: 12px;
}

.schalter input {
  width: auto;
}

.kommando {
  display: flex;
  align-items: center;
  gap: 8px;
  background: var(--flaeche-2);
  border-radius: 6px;
  padding: 4px 8px;
  overflow-x: auto;
}

.kommando code {
  flex: 1;
  white-space: nowrap;
}

.klein {
  padding: 2px 8px;
  font-size: 12px;
}

.konsole {
  margin: 0;
  background: var(--konsole-bg);
  color: var(--konsole-text);
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.5;
  padding: 10px 12px;
  border-radius: 6px;
  height: 460px;
  overflow: auto;
  white-space: pre;
}

.hinweis {
  color: var(--konsole-hinweis);
  white-space: pre-wrap;
}

.titelzeile {
  color: var(--konsole-kopf);
  font-weight: 600;
}

.trenner {
  color: var(--konsole-dim);
}

.fehler {
  color: var(--konsole-fehler);
}
</style>
