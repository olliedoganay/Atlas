from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    resources_dir = repo_root / "apps" / "atlas" / "src-tauri" / "resources"
    backend_resource_dir = resources_dir / "backend"
    prompt_resource_dir = resources_dir / "prompts"
    build_root = repo_root / "output" / "pyinstaller"
    session_root = Path(tempfile.mkdtemp(prefix="session-", dir=build_root))
    dist_root = session_root / "dist"
    work_root = session_root / "build"
    spec_root = session_root / "spec"

    for path in (backend_resource_dir, prompt_resource_dir):
        if path.exists():
            shutil.rmtree(path, ignore_errors=True)

    build_root.mkdir(parents=True, exist_ok=True)
    _cleanup_old_sessions(build_root, keep=session_root)

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

    try:
        subprocess.run(command, check=True, cwd=repo_root)

        built_backend_dir = dist_root / "atlas-backend"
        if not built_backend_dir.exists():
            raise RuntimeError(f"Backend build output was not created: {built_backend_dir}")

        shutil.copytree(built_backend_dir, backend_resource_dir, dirs_exist_ok=True)
        shutil.copytree(repo_root / "prompts", prompt_resource_dir, dirs_exist_ok=True)
    finally:
        shutil.rmtree(session_root, ignore_errors=True)
    return 0


def _cleanup_old_sessions(build_root: Path, *, keep: Path) -> None:
    for path in build_root.glob("session-*"):
        if path == keep:
            continue
        shutil.rmtree(path, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
