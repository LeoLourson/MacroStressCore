import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

// In development the API runs separately; in production FastAPI serves this build itself.
const api = process.env.MSA_API_URL ?? 'http://127.0.0.1:8091';

export default defineConfig({
  plugins: [react()],
  // Behind a reverse proxy under a path prefix: MSA_WEB_BASE=/p/<token>/ at build time.
  base: process.env.MSA_WEB_BASE ?? '/',
  // One bundle for an intranet app is fine; the warning threshold is for public sites.
  build: { chunkSizeWarningLimit: 1200 },
  server: { proxy: { '/v1': { target: api, changeOrigin: true } } },
});
