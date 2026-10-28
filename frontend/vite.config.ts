import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

const apiTarget = process.env.ISO_API_URL ?? 'http://127.0.0.1:8000'

export default defineConfig({
  plugins: [react()],
  build: {
    // Herramienta local: MUI ocupa la mayor parte del paquete principal; Cytoscape va aparte.
    chunkSizeWarningLimit: 800,
  },
  server: {
    host: '127.0.0.1',
    port: 5173,
    proxy: {
      '/api': { target: apiTarget, changeOrigin: false },
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    testTimeout: 15000, // por encima del asyncUtilTimeout de setup.ts
  },
})
