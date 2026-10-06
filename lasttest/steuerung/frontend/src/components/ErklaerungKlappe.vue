<script setup>
import { computed } from 'vue'

// Ausführliche Erklärung je Szenario (lasttest/erklaerungen.py), standardmäßig zugeklappt,
// damit sie im Workshop nichts vorwegnimmt.
const props = defineProps({
  erklaerung: { type: Object, required: true },
})

const abschnitte = [
  ['passiert', 'Was passiert'],
  ['warum', 'Warum es passiert'],
  ['verhindern', 'Wie man es verhindert'],
]

function escape(text) {
  return text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

function inline(text) {
  return escape(text).replace(/`([^`]+)`/g, '<code>$1</code>')
}

// Absätze durch Leerzeile, Zeilen mit „- " werden zu einer Liste
function alsHtml(text) {
  return text
    .trim()
    .split(/\n\s*\n/)
    .map((block) => {
      const zeilen = block.split('\n')
      if (zeilen.every((z) => z.trimStart().startsWith('- '))) {
        return `<ul>${zeilen.map((z) => `<li>${inline(z.trimStart().slice(2))}</li>`).join('')}</ul>`
      }
      const erste = zeilen.findIndex((z) => z.trimStart().startsWith('- '))
      if (erste > 0 && zeilen.slice(erste).every((z) => z.trimStart().startsWith('- '))) {
        return (
          `<p>${inline(zeilen.slice(0, erste).join(' '))}</p>` +
          `<ul>${zeilen.slice(erste).map((z) => `<li>${inline(z.trimStart().slice(2))}</li>`).join('')}</ul>`
        )
      }
      return `<p>${inline(zeilen.join(' '))}</p>`
    })
    .join('')
}

const html = computed(() =>
  abschnitte
    .filter(([schluessel]) => props.erklaerung[schluessel])
    .map(([schluessel, titel]) => ({ schluessel, titel, html: alsHtml(props.erklaerung[schluessel]) })),
)
</script>

<template>
  <details class="klappe">
    <summary>
      <span class="pfeil" aria-hidden="true">▸</span>
      Auflösung: was passiert, warum, wie verhindern
      <span class="hinweis">zugeklappt, um nichts vorwegzunehmen</span>
    </summary>
    <div class="inhalt">
      <section v-for="a in html" :key="a.schluessel" :class="['abschnitt', a.schluessel]">
        <h3>{{ a.titel }}</h3>
        <div class="text" v-html="a.html" />
      </section>
    </div>
  </details>
</template>

<style scoped>
.klappe {
  border: 1px solid var(--rand);
  border-radius: 6px;
  background: var(--flaeche-2);
}

summary {
  display: flex;
  align-items: baseline;
  gap: 8px;
  flex-wrap: wrap;
  padding: 8px 12px;
  cursor: pointer;
  font-weight: 600;
  list-style: none;
  user-select: none;
}

summary::-webkit-details-marker {
  display: none;
}

.pfeil {
  display: inline-block;
  transition: transform 0.15s;
  color: var(--akzent);
}

.klappe[open] .pfeil {
  transform: rotate(90deg);
}

.hinweis {
  font-weight: 400;
  font-size: 12px;
  color: var(--text-2);
}

.inhalt {
  padding: 4px 16px 14px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  background: var(--flaeche);
  border-top: 1px solid var(--rand);
  border-radius: 0 0 6px 6px;
}

.abschnitt {
  border-left: 3px solid var(--rand);
  padding-left: 12px;
}

.abschnitt.passiert {
  border-left-color: var(--akzent);
}

.abschnitt.warum {
  border-left-color: var(--warn);
}

.abschnitt.verhindern {
  border-left-color: var(--gut);
}

h3 {
  margin: 10px 0 4px;
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--text-2);
}

.text :deep(p) {
  margin: 0 0 8px;
  max-width: 90ch;
}

.text :deep(ul) {
  margin: 0 0 8px;
  padding-left: 20px;
  max-width: 90ch;
}

.text :deep(li) {
  margin-bottom: 3px;
}

.text :deep(code) {
  background: var(--flaeche-2);
  border-radius: 4px;
  padding: 1px 4px;
  font-family: var(--mono);
  font-size: 12.5px;
}
</style>
