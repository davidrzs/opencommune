import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';
declare const process: { env: Record<string, string | undefined> };
// In development and preview the API comes from the Rust server (or API_ORIGIN).
const api = process.env.API_ORIGIN || 'http://127.0.0.1:8000';
const proxy = { '/api': api, '/original': api };
export default defineConfig({
  plugins: [sveltekit()],
  server: { port: 5173, strictPort: true, proxy },
  preview: { proxy }
});
