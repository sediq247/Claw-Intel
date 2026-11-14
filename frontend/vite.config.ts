import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({ plugins: [react(), tailwindcss()], css: { postcss: { plugins: [] } }, server: { host: '0.0.0.0', port: 6548, strictPort: true, proxy: { '/api': 'http://localhost:8000', '/ws': { target: 'ws://localhost:8000', ws: true } } }, preview: { host: '0.0.0.0', port: 6548, strictPort: true } })
