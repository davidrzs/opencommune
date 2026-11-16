import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';
declare const process: { env: Record<string, string | undefined> };
// In development and preview the API comes from the Rust server (or API_ORIGIN).
const api = process.env.API_ORIGIN || 'http://127.0.0.1:8000';
const target = { target: api, changeOrigin: true };
const proxy = { '/api': target, '/original': target };
// Extra host names the dev server answers to (comma-separated), e.g. to open it from another machine.
const allowedHosts = process.env.ALLOWED_HOSTS?.split(',');
export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  server: { port: 5173, strictPort: true, proxy, allowedHosts },
  preview: { proxy, allowedHosts }
});
