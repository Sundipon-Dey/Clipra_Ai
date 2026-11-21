import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
  build: { rollupOptions: { input: ['index.html', 'caption-renderer.html'] } },
  test: { environment: 'jsdom', setupFiles: ['./src/testSetup.ts'] },
})
