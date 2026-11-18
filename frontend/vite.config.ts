import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { execSync } from 'node:child_process';
import { defineConfig } from 'vite';
// In development and preview the API comes from the Rust server (or API_ORIGIN).
const api = process.env.API_ORIGIN || 'http://127.0.0.1:8000';
const target = { target: api, changeOrigin: true };
const proxy = { '/api': target, '/original': target };
// Extra host names the dev server answers to (comma-separated), e.g. to open it from another machine.
const allowedHosts = process.env.ALLOWED_HOSTS?.split(',');
// The commit the site is built from, for the footer (src/lib/release.ts): its short hash, and
// whether tracked files differ from it. Without git the hash is empty and the footer leaves it out.
function release(): { commit: string; dirty: boolean } {
  const git = (args: string) =>
    execSync(`git ${args}`, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'ignore'] }).trim();
  try {
    const commit = git('rev-parse --short=7 HEAD');
    return { commit, dirty: git('status --porcelain --untracked-files=no') !== '' };
  } catch {
    return { commit: '', dirty: false };
  }
}
export default defineConfig({
  plugins: [tailwindcss(), sveltekit()],
  define: { __RELEASE__: JSON.stringify(release()) },
  server: { port: 5173, strictPort: true, proxy, allowedHosts },
  preview: { proxy, allowedHosts }
});
