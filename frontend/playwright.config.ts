import { defineConfig } from "@playwright/test";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

// End-to-end tests run the real backend (fresh SQLite database) and the Vite dev server.
const backendDir = resolve(import.meta.dirname, "../backend");
const python =
  process.env.GHOSTTRACE_PYTHON ??
  (process.platform === "win32" ? join(backendDir, ".venv", "Scripts", "python.exe") : join(backendDir, ".venv", "bin", "python"));
// The config is evaluated again in each worker, so pick the database path once and pass it on.
process.env.GHOSTTRACE_E2E_DB ??= join(tmpdir(), `ghosttrace-e2e-${Date.now()}.db`);
const dbPath = process.env.GHOSTTRACE_E2E_DB;
const API_PORT = 8765;
const WEB_PORT = 5180;

export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    // Use the locally installed Edge/Chrome when available; CI installs Playwright Chromium.
    channel: process.env.PW_CHANNEL === "bundled" ? undefined : (process.env.PW_CHANNEL ?? "msedge"),
    viewport: { width: 1440, height: 900 },
    acceptDownloads: true,
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: `"${python}" -m uvicorn app.main:app --host 127.0.0.1 --port ${API_PORT}`,
      cwd: backendDir,
      url: `http://127.0.0.1:${API_PORT}/api/v1/ready`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        GHOSTTRACE_DATABASE_URL: `sqlite:///${dbPath.replace(/\\/g, "/")}`,
        GHOSTTRACE_RATE_LIMIT_PER_MINUTE: "0",
        GHOSTTRACE_RETENTION_HOURS: "0",
        GHOSTTRACE_LOG_LEVEL: "WARNING",
      },
    },
    {
      command: `npm run dev -- --host 127.0.0.1 --port ${WEB_PORT} --strictPort`,
      url: `http://127.0.0.1:${WEB_PORT}`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: { GHOSTTRACE_API_PROXY: `http://127.0.0.1:${API_PORT}` },
    },
  ],
});
