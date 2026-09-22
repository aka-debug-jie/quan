import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 4173 },
  build: { sourcemap: false },
  test: {
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    environment: 'jsdom',
    setupFiles: './src/test-setup.ts',
    coverage: { provider: 'v8', reporter: ['text', 'json-summary'] },
  },
})
