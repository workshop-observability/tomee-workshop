<script setup>
import { computed, ref } from 'vue'

const props = defineProps({
  szenarien: { type: Array, required: true },
  kommandos: { type: Array, required: true },
  auswahl: { type: String, default: null },
  aktiv: { type: Set, required: true }, // Schlüssel mit laufendem Lauf
})
const emit = defineEmits(['waehlen'])

const suche = ref('')

const gruppen = computed(() => {
  const s = suche.value.trim().toLowerCase()
  const treffer = props.szenarien.filter(
    (sz) => !s || `${sz.id} ${sz.titel} ${sz.modul}`.toLowerCase().includes(s),
  )
  const nachModul = new Map()
  for (const sz of treffer) {
    if (!nachModul.has(sz.modul)) nachModul.set(sz.modul, [])
    nachModul.get(sz.modul).push(sz)
  }
  return [...nachModul.entries()]
})
</script>

<template>
  <nav class="liste">
    <input v-model="suche" type="search" placeholder="Szenario suchen (ID, Titel, Modul)" />

    <section v-for="[modul, eintraege] in gruppen" :key="modul">
      <h3>{{ modul }}</h3>
      <button
        v-for="sz in eintraege"
        :key="sz.id"
        class="eintrag"
        :class="{ gewaehlt: auswahl === sz.id }"
        @click="emit('waehlen', sz.id)"
      >
        <span class="kennung">{{ sz.id }}</span>
        <span class="titel">{{ sz.titel }}</span>
        <span v-if="aktiv.has(sz.id)" class="punkt laeuft" title="läuft" />
      </button>
    </section>

    <section>
      <h3>Freie Kommandos</h3>
      <button
        v-for="k in kommandos"
        :key="k.art"
        class="eintrag"
        :class="{ gewaehlt: auswahl === `cmd:${k.art}` }"
        @click="emit('waehlen', `cmd:${k.art}`)"
      >
        <span class="kennung">{{ k.art === 'reset' ? '↺' : '⚙' }}</span>
        <span class="titel">{{ k.titel }}</span>
        <span v-if="aktiv.has(`cmd:${k.art}`)" class="punkt laeuft" title="läuft" />
      </button>
    </section>
  </nav>
</template>

<style scoped>
.liste {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

h3 {
  margin: 14px 4px 4px;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-2);
}

.eintrag {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  text-align: left;
  border: 1px solid transparent;
  background: transparent;
  padding: 6px 8px;
}

.eintrag:hover {
  background: var(--flaeche-2);
}

.eintrag.gewaehlt {
  background: color-mix(in srgb, var(--akzent) 12%, var(--flaeche));
  border-color: color-mix(in srgb, var(--akzent) 45%, transparent);
}

.kennung {
  font-family: var(--mono);
  font-size: 12px;
  font-weight: 600;
  color: var(--akzent);
  min-width: 30px;
}

.titel {
  flex: 1;
  min-width: 0;
}
</style>
