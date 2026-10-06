import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// Entwicklung: "npm run dev" – die API kommt vom lokal gestarteten server.py (Port 8070)
export default defineConfig({
  // Relative Pfade zu den gebauten Dateien: die Oberfläche läuft dadurch sowohl
  // direkt unter http://<host>:8070/ als auch hinter dem Portal unter
  // http://<host>:8080/frontend/ (siehe code-demo/portal/nginx.conf).
  base: './',
  plugins: [vue()],
  server: {
    proxy: { '/api': 'http://localhost:8070' },
  },
})
