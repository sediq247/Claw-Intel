import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  css: { postcss: { plugins: [] } },
  server: { host: '0.0.0.0', port: 6548, strictPort: true, proxy: { '/api': 'http://localhost:8000', '/ws': { target: 'ws://localhost:8000', ws: true } } },
  preview: { host: '0.0.0.0', port: 6548, strictPort: true },
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('/node_modules/viem/') || id.includes('/node_modules/wagmi/') || id.includes('/node_modules/@wagmi/') || id.includes('/node_modules/@walletconnect/')) return 'wallet-vendor'
          if (id.includes('/node_modules/')) return 'vendor'
        },
      },
    },
  },
})
