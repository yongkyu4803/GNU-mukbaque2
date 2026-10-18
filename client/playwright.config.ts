import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  use: {
    baseURL: "http://127.0.0.1:8002",
    viewport: { width: 1440, height: 1050 },
    trace: "retain-on-failure",
  },
  webServer: {
    command: "../.venv/bin/python ../tools/test_web_server.py --port 8002",
    url: "http://127.0.0.1:8002/api/v1/health/ready",
    reuseExistingServer: false,
    timeout: 30000,
  },
});
