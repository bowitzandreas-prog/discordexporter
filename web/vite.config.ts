import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';

// Gebaute Oberfläche landet im Python-Paket, damit Nutzer kein Node brauchen.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  base: '/',
  build: {
    outDir: '../dcexport/web_dist',
    emptyOutDir: true,
    assetsInlineLimit: 0,
    chunkSizeWarningLimit: 800
  },
  server: {
    proxy: { '/api': 'http://127.0.0.1:8765' }
  }
});
