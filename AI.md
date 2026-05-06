# Atlas Repo Note

- Repo: `olliedoganay/Atlas.Chat`
- Current version: `1.0.27`
- Stack: Tauri + React frontend, Rust shell, Python FastAPI backend, Ollama, Docker code runner.

## Main Paths

- UI: `apps/atlas/src`
- Tauri shell/backend launcher: `apps/atlas/src-tauri/src/lib.rs`
- Backend API/service: `src/atlas_local/api.py`, `src/atlas_local/api_service.py`
- Code runner: `src/atlas_local/code_runner.py`
- Tests: `tests`, `apps/atlas/src/**/*.test.ts*`

## Commands

- Start source app: `.\scripts\start_atlas_dev.ps1`
- Version check: `node scripts\run_repo_python.mjs scripts\check_atlas_version.py --tag v1.0.27`
- Frontend/release build: `cd apps\atlas && npm run build:release`
- Rust check: `cargo check --manifest-path apps\atlas\src-tauri\Cargo.toml`
- Backend focused tests: `.\.venv\Scripts\python.exe -m pytest tests\test_api.py tests\test_api_service.py tests\test_code_runner.py tests\test_run_store.py`

## Releases

- Windows MSI: `.github/workflows/release-windows.yml`
- Linux `.deb` + AppImage: `.github/workflows/release-linux.yml`
- Release tags must match manifest versions, for example `v1.0.27`.
- Safe release sequence:
  1. Commit all app fixes first.
  2. Bump every manifest version.
  3. Commit the release change.
  4. Tag it: `git tag -a vX.Y.Z -m "Atlas vX.Y.Z"`.
  5. Push `main`, then push the tag.
