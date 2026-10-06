<script setup>
import { fehlerVon } from '../parameterPruefung.js'

const props = defineProps({
  parameter: { type: Array, required: true },
  werte: { type: Object, required: true },
})
const emit = defineEmits(['aendern'])

function setzen(name, wert) {
  emit('aendern', { ...props.werte, [name]: wert })
}

function eingabe(p, ereignis) {
  const roh = ereignis.target.value
  if (p.typ === 'ganzzahl' || p.typ === 'zahl') {
    setzen(p.name, roh === '' ? '' : Number(roh))
  } else {
    setzen(p.name, roh)
  }
}

function geaendert(p) {
  return props.werte[p.name] !== undefined && props.werte[p.name] !== p.standard
}
</script>

<template>
  <div v-if="parameter.length" class="raster">
    <label v-for="p in parameter" :key="p.name" class="feld" :class="{ geaendert: geaendert(p) }">
      <span class="beschriftung">
        {{ p.text }}
        <code class="name">{{ p.name }}</code>
      </span>

      <span class="eingabe">
        <select v-if="p.typ === 'auswahl'" :value="werte[p.name]" @change="eingabe(p, $event)">
          <option v-for="a in p.auswahl" :key="a" :value="a">{{ a }}</option>
        </select>
        <input
          v-else-if="p.typ === 'ganzzahl' || p.typ === 'zahl'"
          type="number"
          :value="werte[p.name]"
          :min="p.min ?? undefined"
          :max="p.max ?? undefined"
          :step="p.typ === 'ganzzahl' ? 1 : 'any'"
          @input="eingabe(p, $event)"
        />
        <input v-else type="text" :value="werte[p.name]" @input="eingabe(p, $event)" />
        <span v-if="p.einheit" class="einheit">{{ p.einheit }}</span>
      </span>

      <span class="fusszeile">
        <span v-if="fehlerVon(p, werte[p.name])" class="fehler">{{ fehlerVon(p, werte[p.name]) }}</span>
        <span v-else-if="p.hilfe" class="hilfe">{{ p.hilfe }}</span>
        <span v-else class="hilfe">
          Standard {{ p.standard }}{{ p.einheit ? ' ' + p.einheit : '' }}
          <template v-if="p.min !== null || p.max !== null"> · {{ p.min ?? '…' }}–{{ p.max ?? '…' }}</template>
        </span>
      </span>
    </label>
  </div>
  <p v-else class="leer">Dieses Szenario hat keine einstellbaren Parameter.</p>
</template>

<style scoped>
.raster {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
  gap: 12px 16px;
}

.feld {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.beschriftung {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-weight: 500;
}

.name {
  color: var(--text-2);
  font-weight: 400;
}

.eingabe {
  display: flex;
  align-items: center;
  gap: 6px;
}

.einheit {
  color: var(--text-2);
  font-size: 12px;
  min-width: 18px;
}

.geaendert input,
.geaendert select {
  border-color: var(--akzent);
  background: color-mix(in srgb, var(--akzent) 6%, var(--flaeche));
}

.fusszeile {
  font-size: 12px;
  min-height: 17px;
}

.hilfe {
  color: var(--text-2);
}

.fehler {
  color: var(--schlecht);
}

.leer {
  color: var(--text-2);
  margin: 0;
}
</style>
