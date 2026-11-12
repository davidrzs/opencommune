import { defineConfig } from '@playwright/test';
export default defineConfig({
  testDir: './tests',
  testMatch: 'access.spec.ts',
  workers: 1,
  use: { baseURL: 'http://127.0.0.1:5174', viewport: { width: 1440, height: 1000 } },
  webServer: [
    { command: 'python3 tests/access-fixture.py', port: 8002 },
    {
      // the static build, its API proxied to the fixture
      command: 'npm run build && npx vite preview --host 127.0.0.1 --port 5174 --strictPort',
      port: 5174,
      env: { API_ORIGIN: 'http://127.0.0.1:8002' }
    }
  ]
});
