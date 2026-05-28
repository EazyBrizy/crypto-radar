import { spawn, spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import net from "node:net";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { setTimeout as delay } from "node:timers/promises";

const __filename = fileURLToPath(import.meta.url);
const rootDir = path.resolve(path.dirname(__filename), "..");
const backendDir = path.join(rootDir, "backend");
const frontendDir = path.join(rootDir, "frontend");
const args = parseArgs(process.argv.slice(2));
const requestedBackendPort = Number(args["backend-port"] ?? 8000);
const requestedFrontendPort = Number(args["frontend-port"] ?? 3000);
const killExisting = Boolean(args["kill-existing"]);
const headed = Boolean(args.headed);
const keepOpen = Boolean(args["keep-open"]);
const screenshotPath = path.resolve(rootDir, String(args.screenshot ?? ".codex-app-smoke.png"));
const children = [];

let backendPort = requestedBackendPort;
let frontendPort = requestedFrontendPort;
let browser;

process.on("SIGINT", () => {
  void cleanup().finally(() => process.exit(130));
});
process.on("SIGTERM", () => {
  void cleanup().finally(() => process.exit(143));
});

try {
  backendPort = await reservePort(requestedBackendPort, "backend");
  frontendPort = await reservePort(requestedFrontendPort, "frontend");

  const python = resolvePython();
  const node = process.execPath;
  const backend = spawnManaged(
    python,
    ["-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", String(backendPort)],
    {
      cwd: backendDir,
      env: {
        ...process.env,
        PYTHONPATH: [
          path.join(backendDir, ".venv", "Lib", "site-packages"),
          backendDir,
        ].join(path.delimiter),
        CRYPTO_RADAR_SCANNER_ENABLED: "false",
      },
      name: "backend",
    },
  );
  children.push(backend);

  await waitForHttp(`http://127.0.0.1:${backendPort}/health`, 30);
  const health = await getJson(`http://127.0.0.1:${backendPort}/health`);
  const openSignals = await getJson(`http://127.0.0.1:${backendPort}/api/v1/signals/open`);
  const activeSignals = await getJson(`http://127.0.0.1:${backendPort}/api/v1/signals/active`);

  let previewSummary = "skipped:no-open-signals";
  if (Array.isArray(openSignals) && openSignals.length > 0) {
    const preview = await postJson(
      `http://127.0.0.1:${backendPort}/api/v1/signals/${openSignals[0].id}/execution-preview`,
      {
        mode: "virtual",
        user_id: "demo_user",
        account_balance: 100,
        risk_percent: 10,
        leverage: 1,
        fee_rate: 0,
        slippage_bps: 0,
        simulation_mode: "auto",
        max_virtual_slippage_bps: 150,
        allow_partial_fill: true,
        min_fill_ratio: 0.25,
        max_open_positions: 3,
      },
    );
    if (preview.mode === "impact_aware" && !preview.simulated_path) {
      throw new Error("Impact-aware execution preview did not include simulated_path.");
    }
    previewSummary = [
      preview.mode,
      preview.status,
      `gate=${preview.quality_gate?.status ?? "unknown"}`,
      preview.simulated_path ? "path=decay" : "path=none",
    ].join(":");
  }

  const frontend = spawnManaged(
    node,
    ["node_modules/next/dist/bin/next", "dev", "--hostname", "127.0.0.1", "--port", String(frontendPort)],
    {
      cwd: frontendDir,
      env: {
        ...process.env,
        NEXT_PUBLIC_FASTAPI_HTTP_URL: `http://127.0.0.1:${backendPort}`,
        NEXT_PUBLIC_FASTAPI_WS_URL: `ws://127.0.0.1:${backendPort}/api/v1/realtime/ws`,
      },
      name: "frontend",
    },
  );
  children.push(frontend);

  await waitForHttp(`http://127.0.0.1:${frontendPort}/dashboard/radar`, 45);

  const requireFromFrontend = createRequire(path.join(frontendDir, "package.json"));
  const { chromium } = requireFromFrontend("@playwright/test");
  browser = await chromium.launch({ headless: !headed });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1100 } });
  await page.goto(`http://127.0.0.1:${frontendPort}/dashboard/radar`, { waitUntil: "networkidle" });

  const hasSignals = Array.isArray(openSignals) && openSignals.length > 0;
  if (hasSignals) {
    await page.getByText("Execution Quality", { exact: true }).waitFor({ timeout: 15000 });
    await page.getByText("Post-impact", { exact: true }).waitFor({ timeout: 15000 });
  } else {
    await page.getByText("No active signals yet", { exact: true }).waitFor({ timeout: 15000 });
  }
  await page.screenshot({ path: screenshotPath, fullPage: false });

  const uiText = hasSignals
    ? await page.locator(".execution-quality-block").innerText({ timeout: 5000 })
    : "empty-state";

  const result = {
    ok: true,
    backend: `http://127.0.0.1:${backendPort}`,
    frontend: `http://127.0.0.1:${frontendPort}/dashboard/radar`,
    storage: health.storage?.status ?? "unknown",
    openSignals: Array.isArray(openSignals) ? openSignals.length : 0,
    activeSignals: Array.isArray(activeSignals) ? activeSignals.length : 0,
    preview: previewSummary,
    ui: uiText.split(/\r?\n/).slice(0, 12).join(" | "),
    screenshot: screenshotPath,
  };
  console.log(JSON.stringify(result, null, 2));

  if (keepOpen) {
    console.log("Keeping dev servers open. Press Ctrl+C to stop.");
    await new Promise(() => {});
  }
} catch (error) {
  console.error(JSON.stringify({
    ok: false,
    error: String(error?.stack ?? error),
    logs: children.map((child) => ({
      name: child.smokeName,
      pid: child.pid,
      tail: child.smokeLog.slice(-3000),
    })),
  }, null, 2));
  process.exitCode = 1;
} finally {
  if (!keepOpen) {
    await cleanup();
    await assertPortClosed(backendPort, "backend");
    await assertPortClosed(frontendPort, "frontend");
  }
}

function parseArgs(items) {
  const parsed = {};
  for (let index = 0; index < items.length; index += 1) {
    const item = items[index];
    if (!item.startsWith("--")) continue;
    const key = item.slice(2);
    const next = items[index + 1];
    if (!next || next.startsWith("--")) {
      parsed[key] = true;
    } else {
      parsed[key] = next;
      index += 1;
    }
  }
  return parsed;
}

async function reservePort(port, label) {
  if (!(await isPortBusy(port))) return port;
  if (killExisting) {
    await killPort(port);
    await waitForPortClosed(port, 10);
    if (!(await isPortBusy(port))) return port;
  }

  const fallback = await nextFreePort(port + 1);
  console.warn(`${label} port ${port} is busy; using ${fallback} for this smoke run.`);
  return fallback;
}

function resolvePython() {
  const candidates = [
    process.env.CRYPTO_RADAR_BACKEND_PYTHON,
    path.join(backendDir, ".venv", "Scripts", "python.exe"),
    path.join(os.homedir(), ".cache", "codex-runtimes", "codex-primary-runtime", "dependencies", "python", "python.exe"),
    "python",
  ].filter(Boolean);

  for (const candidate of candidates) {
    const result = spawnSync(candidate, ["-c", "import sys; raise SystemExit(0)"], {
      cwd: backendDir,
      stdio: "ignore",
      shell: false,
    });
    if (result.status === 0) return candidate;
  }
  throw new Error("No runnable Python found for backend smoke test.");
}

function spawnManaged(command, commandArgs, options) {
  const child = spawn(command, commandArgs, {
    cwd: options.cwd,
    env: normalizeWindowsEnv(options.env),
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.smokeName = options.name;
  child.smokeLog = "";
  child.stdout.on("data", (chunk) => {
    child.smokeLog += chunk.toString();
  });
  child.stderr.on("data", (chunk) => {
    child.smokeLog += chunk.toString();
  });
  child.on("exit", (code, signal) => {
    child.smokeExit = { code, signal };
  });
  return child;
}

function normalizeWindowsEnv(env) {
  if (process.platform !== "win32") return env;
  const normalized = { ...env };
  const pathKeys = Object.keys(normalized).filter((key) => key.toLowerCase() === "path");
  if (pathKeys.length <= 1) return normalized;
  const preferred = pathKeys.find((key) => key === "Path") ?? pathKeys[0];
  const value = normalized[preferred];
  for (const key of pathKeys) {
    if (key !== preferred) delete normalized[key];
  }
  normalized[preferred] = value;
  return normalized;
}

async function waitForHttp(url, timeoutSeconds) {
  const deadline = Date.now() + timeoutSeconds * 1000;
  let lastError = "";
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.status >= 200 && response.status < 500) return response;
      lastError = `${response.status} ${response.statusText}`;
    } catch (error) {
      lastError = String(error);
    }
    await delay(500);
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError}`);
}

async function getJson(url) {
  const response = await fetch(url);
  if (!response.ok) throw new Error(`GET ${url} failed: ${response.status}`);
  return response.json();
}

async function postJson(url, body) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) throw new Error(`POST ${url} failed: ${response.status} ${await response.text()}`);
  return response.json();
}

async function isPortBusy(port) {
  return new Promise((resolve) => {
    const server = net.createServer();
    server.once("error", () => resolve(true));
    server.once("listening", () => {
      server.close(() => resolve(false));
    });
    server.listen(port, "127.0.0.1");
  });
}

async function nextFreePort(start) {
  for (let port = start; port < start + 100; port += 1) {
    if (!(await isPortBusy(port))) return port;
  }
  throw new Error(`No free TCP port found after ${start}`);
}

async function killPort(port) {
  if (process.platform !== "win32") return;
  const command = [
    "$ErrorActionPreference='SilentlyContinue'",
    `$pids = Get-NetTCPConnection -LocalPort ${port} -State Listen | Select-Object -ExpandProperty OwningProcess -Unique`,
    "foreach ($pid in $pids) { if ($pid) { taskkill.exe /PID $pid /T /F | Out-Null } }",
  ].join("; ");
  spawnSync("powershell", ["-NoProfile", "-Command", command], { stdio: "ignore" });
}

async function cleanup() {
  if (browser) {
    await browser.close().catch(() => {});
    browser = undefined;
  }
  for (const child of [...children].reverse()) {
    await killTree(child);
  }
}

async function killTree(child) {
  if (!child || !child.pid) return;
  if (process.platform === "win32") {
    spawnSync("taskkill.exe", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    if (child.exitCode === null && !child.killed) {
      child.kill("SIGKILL");
    }
  } else if (child.exitCode === null && !child.killed) {
    child.kill("SIGTERM");
  }
  await waitForChildExit(child, 5000);
}

async function waitForChildExit(child, timeoutMs) {
  if (child.exitCode !== null) return;
  await Promise.race([
    new Promise((resolve) => child.once("exit", resolve)),
    delay(timeoutMs),
  ]);
}

async function waitForPortClosed(port, timeoutSeconds) {
  const deadline = Date.now() + timeoutSeconds * 1000;
  while (Date.now() < deadline) {
    if (!(await isPortListening(port))) return true;
    await delay(300);
  }
  return false;
}

async function assertPortClosed(port, label) {
  if (await waitForPortClosed(port, 5)) return;
  await killPort(port);
  if (await waitForPortClosed(port, 30)) return;
  throw new Error(`${label} port ${port} is still busy after smoke cleanup.`);
}

async function isPortListening(port) {
  return new Promise((resolve) => {
    const socket = net.createConnection({ host: "127.0.0.1", port });
    socket.once("connect", () => {
      socket.destroy();
      resolve(true);
    });
    socket.once("error", () => resolve(false));
    socket.setTimeout(1000, () => {
      socket.destroy();
      resolve(false);
    });
  });
}
