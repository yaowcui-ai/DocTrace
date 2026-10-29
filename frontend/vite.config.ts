import { defineConfig } from 'vite';

export default defineConfig({
  base: '/workspace/',
  server: {proxy: {'/auth': 'http://127.0.0.1:8001', '/api': 'http://127.0.0.1:8001'}},
});
