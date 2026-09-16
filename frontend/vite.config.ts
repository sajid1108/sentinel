import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// Minimal declaration so tsc accepts process.env without adding @types/node as a dependency.
declare const process: { env: Record<string, string | undefined> }

const internalKey = process.env.SENTINEL_INTERNAL_API_KEY ?? 'sentinel-internal-dev-key'
const apiProxy = {
  target: 'http://127.0.0.1:8000',
  changeOrigin: true,
  headers: { 'X-Internal-Key': internalKey },
}

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
  ],
  server: {
    proxy: {
      '/api': apiProxy,
      '/health': apiProxy,
    },
  },
  preview: {
    proxy: {
      '/api': apiProxy,
      '/health': apiProxy,
    },
  },
})
