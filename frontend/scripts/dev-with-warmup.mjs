import { spawn } from "node:child_process";

const DEFAULT_PORT = 3000;
const WARMUP_ROUTES = [
  "/",
  "/dashboard/radar",
  "/dashboard/watchlist",
  "/dashboard/trades/active",
  "/dashboard/trades/journal",
  "/dashboard/trades/analytics",
  "/dashboard/settings"
];

const args = process.argv.slice(2);
const port = readPort(args) ?? Number(process.env.PORT || DEFAULT_PORT);
const host = process.env.NEXT_DEV_HOST ?? "127.0.0.1";
const origin = `http://${host}:${port}`;
const nextBin = process.platform === "win32" ? "next.cmd" : "next";

const child = spawn(nextBin, ["dev", ...args], {
  cwd: process.cwd(),
  env: process.env,
  shell: process.platform === "win32",
  stdio: "inherit"
});

let shuttingDown = false;

child.on("exit", (code, signal) => {
  if (shuttingDown) return;
  if (signal) {
    process.kill(process.pid, signal);
    return;
  }
  process.exit(code ?? 0);
});

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    shuttingDown = true;
    child.kill(signal);
  });
}

void warmRoutesWhenReady(origin);

async function warmRoutesWhenReady(baseUrl) {
  const ready = await waitForServer(baseUrl, 60_000);
  if (!ready) {
    console.warn("[dev-warmup] Next dev server did not respond in time; skipping route warmup.");
    return;
  }

  console.log(`[dev-warmup] Warming ${WARMUP_ROUTES.length} routes to avoid first-click compile stalls...`);

  for (const route of WARMUP_ROUTES) {
    const startedAt = Date.now();
    try {
      await fetch(`${baseUrl}${route}`, {
        redirect: "manual",
        headers: {
          "x-dev-warmup": "1"
        }
      });
      console.log(`[dev-warmup] ${route} ${Date.now() - startedAt}ms`);
    } catch (error) {
      console.warn(`[dev-warmup] ${route} failed: ${error instanceof Error ? error.message : String(error)}`);
    }
  }

  console.log("[dev-warmup] Dashboard routes are warm.");
}

async function waitForServer(baseUrl, timeoutMs) {
  const deadline = Date.now() + timeoutMs;

  while (Date.now() < deadline) {
    try {
      const response = await fetch(baseUrl, { redirect: "manual" });
      if (response.status < 500) return true;
    } catch {
      // Server is still booting.
    }
    await sleep(300);
  }

  return false;
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function readPort(argv) {
  for (let index = 0; index < argv.length; index += 1) {
    const arg = argv[index];
    if ((arg === "--port" || arg === "-p") && argv[index + 1]) return Number(argv[index + 1]);
    if (arg?.startsWith("--port=")) return Number(arg.slice("--port=".length));
  }
  return null;
}
