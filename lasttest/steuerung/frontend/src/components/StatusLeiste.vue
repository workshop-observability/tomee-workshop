<script setup>
import { onBeforeUnmount, ref, watch } from 'vue'
import { api } from '../api.js'

// Live-Ampel wie "mes_last.py status --sperren --haproxy"; fragt dieselbe Diagnose ab.
const aktiv = ref(true)
const status = ref(null)
const fehler = ref('')
let timer = null

async function laden() {
  try {
    status.value = await api.status()
    fehler.value = ''
  } catch (e) {
    fehler.value = e.message
  }
}

function planen() {
  clearInterval(timer)
  if (aktiv.value) {
    laden()
    timer = setInterval(laden, 5000)
  }
}

watch(aktiv, planen, { immediate: true })
onBeforeUnmount(() => clearInterval(timer))
</script>

<template>
  <section class="karte status">
    <div class="kopf">
      <h2>Live-Status</h2>
      <span v-if="status" class="zeit">{{ status.zeit }}</span>
      <label class="schalter"><input v-model="aktiv" type="checkbox" /> alle 5 s</label>
    </div>
    <p v-if="fehler" class="fehler">Status nicht abrufbar: {{ fehler }}</p>
    <div v-if="aktiv && status" class="zeilen">
      <div v-for="r in status.rollen" :key="r.rolle" class="zeile">
        <span class="punkt" :class="r.erreichbar ? 'laeuft' : 'fehler'" />
        <code>{{ r.text }}</code>
      </div>
      <div class="zeile"><span class="punkt aus" /><code>{{ status.oracle }}</code></div>
      <div class="zeile"><span class="punkt aus" /><code>{{ status.haproxy }}</code></div>
    </div>
  </section>
</template>

<style scoped>
.status {
  padding: 12px 14px;
}

.kopf {
  display: flex;
  align-items: center;
  gap: 12px;
}

h2 {
  margin: 0;
  font-size: 14px;
}

.zeit {
  color: var(--text-2);
  font-family: var(--mono);
  font-size: 12px;
}

.schalter {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 4px;
  color: var(--text-2);
  font-size: 12px;
}

.schalter input {
  width: auto;
}

.zeilen {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  overflow-x: auto;
}

.zeile {
  display: flex;
  align-items: center;
  gap: 8px;
  white-space: nowrap;
}

.fehler {
  color: var(--schlecht);
  margin: 8px 0 0;
}
</style>
