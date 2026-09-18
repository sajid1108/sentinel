/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // The dashboard renders every time in Asia/Kolkata (1.5). Running the suite in UTC is what makes
    // that assertion mean something: in IST a bug that uses the browser's zone would pass.
    env: { TZ: 'UTC' },
    include: ['src/**/*.test.{ts,tsx}'],
  },
})
