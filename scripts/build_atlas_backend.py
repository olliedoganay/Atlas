from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    resources_dir = repo_root / "apps" / "atlas" / "src-tauri" / "resources"
    backend_resource_dir = resources_dir / "backend"
    prompt_resource_dir = resources_dir / "prompts"
    build_root = repo_root / "output" / "pyinstaller"
    dist_root = build_root / "dist"
    work_root = build_root / "build"
    spec_root = build_root / "spec"

    for path in (backend_resource_dir, prompt_resource_dir):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    for path in (resources_dir, dist_root, work_root, spec_root):
        path.mkdir(parents=True, exist_ok=True)

    command = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--onedir",
        "--name",
        "atlas-backend",
        "--distpath",
        str(dist_root),
        "--workpath",
        str(work_root),
        "--specpath",
        str(spec_root),
        "--paths",
        str(repo_root / "src"),
        "--collect-submodules",
        "atlas_local",
        "--collect-submodules",
        "uvicorn",
        "--collect-submodules",
        "mem0",
        "--collect-submodules",
        "qdrant_client",
        "--copy-metadata",
        "mem0ai",
        "--copy-metadata",
        "langgraph",
        "--copy-metadata",
        "langchain-ollama",
        "--copy-metadata",
        "fastapi",
        "--copy-metadata",
        "uvicorn",
        str(repo_root / "src" / "atlas_local" / "backend_entry.py"),
    ]

    subprocess.run(command, check=True, cwd=repo_root)

    built_backend_dir = dist_root / "atlas-backend"
    if not built_backend_dir.exists():
        raise RuntimeError(f"Backend build output was not created: {built_backend_dir}")

    shutil.copytree(built_backend_dir, backend_resource_dir, dirs_exist_ok=True)
    shutil.copytree(repo_root / "prompts", prompt_resource_dir, dirs_exist_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
