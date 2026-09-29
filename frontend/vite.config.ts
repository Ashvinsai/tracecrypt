import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// The investigator workspace talks to the FastAPI app on the same origin when
// served at /investigator. In `vite dev` the proxy forwards API calls to the
// local API (make dev → :8000, make demo → :8010).
const API_TARGET = process.env.VITE_API_PROXY ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  base: '/investigator/',
  server: {
    proxy: {
      '/api': API_TARGET,
      '/healthz': API_TARGET,
      '/readyz': API_TARGET,
    },
  },
  test: {
    environment: 'jsdom',
    globals: false,
    setupFiles: ['./src/test/setup.ts'],
    css: false,
  },
})
