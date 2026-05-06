#!/usr/bin/env node
import { existsSync } from "node:fs";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(scriptDir, "..");
const args = process.argv.slice(2);

if (args.length === 0) {
  console.error("Usage: node scripts/run_repo_python.mjs <script> [args...]");
  process.exit(2);
}

const python = resolvePython();
const script = path.resolve(process.cwd(), args[0]);
const result = spawnSync(python, [script, ...args.slice(1)], {
  cwd: repoRoot,
  env: process.env,
  stdio: "inherit",
});

if (result.error) {
  console.error(result.error.message);
  process.exit(1);
}

process.exit(result.status ?? 1);

function resolvePython() {
  if (process.env.PYTHON && process.env.PYTHON.trim()) {
    return process.env.PYTHON.trim();
  }

  const candidates =
    process.platform === "win32"
      ? [
          path.join(repoRoot, ".venv", "Scripts", "python.exe"),
          path.join(repoRoot, ".venv", "Scripts", "python"),
          "python",
        ]
      : [
          path.join(repoRoot, ".venv", "bin", "python"),
          path.join(repoRoot, ".venv", "bin", "python3"),
          "python3",
          "python",
        ];

  return candidates.find((candidate) => candidate.includes(path.sep) ? existsSync(candidate) : true) ?? "python";
}
