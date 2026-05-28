import { mkdirSync, writeFileSync } from "node:fs";
import os from "node:os";
import { dirname, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const frontendDir = process.cwd();
const backendDir = resolve(frontendDir, "../backend");
const outputPath = resolve(frontendDir, "src/api/generated/openapi.json");
const httpBaseUrl = process.env.NEXT_PUBLIC_FASTAPI_HTTP_URL ?? "http://127.0.0.1:8000";

const schema = (await fetchSchemaFromServer(httpBaseUrl)) ?? exportSchemaFromFastApiApp();

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(outputPath, `${JSON.stringify(schema, null, 2)}\n`, "utf8");
console.log(`OpenAPI schema written to ${outputPath}`);

async function fetchSchemaFromServer(baseUrl) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 2500);

  try {
    const response = await fetch(`${baseUrl.replace(/\/$/, "")}/openapi.json`, {
      signal: controller.signal
    });
    if (!response.ok) return null;
    return await response.json();
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}

function exportSchemaFromFastApiApp() {
  const pythonCandidates = [
    process.env.CRYPTO_RADAR_BACKEND_PYTHON,
    resolve(frontendDir, "../.venv/Scripts/python.exe"),
    resolve(frontendDir, "../backend/.venv/Scripts/python.exe"),
    resolve(os.homedir(), ".cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe"),
    "python"
  ].filter(Boolean);

  const command = [
    "import json",
    "from app.main import app",
    "print(json.dumps(app.openapi(), ensure_ascii=False))"
  ].join("; ");

  for (const python of pythonCandidates) {
    const result = spawnSync(python, ["-c", command], {
      cwd: backendDir,
      env: {
        ...process.env,
        PYTHONPATH: [
          resolve(backendDir, ".venv/Lib/site-packages"),
          backendDir,
        ].join(process.platform === "win32" ? ";" : ":"),
      },
      encoding: "utf8"
    });

    if (result.status === 0 && result.stdout.trim()) {
      return JSON.parse(result.stdout);
    }
  }

  throw new Error("Could not export OpenAPI schema from running FastAPI server or local app import.");
}
