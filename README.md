# Atlas

Atlas is a local-first desktop chat workspace for Ollama. It runs a Tauri desktop shell on top of a Python backend, keeps thread history on your machine, and lets each thread stay pinned to its chosen model once the conversation begins.

## Highlights

- chat with local Ollama models in a desktop UI
- lock model and temperature per thread after the first message
- keep thread history and draft chats
- enable optional cross-chat memory and manual memory controls
- run everything locally with a small surface area: `Workspace` and `Settings`

## Stack

- desktop shell: Tauri, React, Vite
- backend: Python, FastAPI, LangGraph
- model runtime: Ollama
- local state: `.data/`

## Requirements

- Windows 10/11 with PowerShell
- Python 3.11+
- Node.js 20+
- Rust stable toolchain with Cargo
- Ollama running locally
- a chat model such as `gpt-oss:20b`
- an embedding model such as `nomic-embed-text:latest`

## Platform Notes

The current repo scripts, CI, launcher wrappers, and packaging flow are Windows-first. The source tree is largely portable, but the documented commands and automated validation currently assume Windows paths, PowerShell, and `.exe` entrypoints.

## Quick Start

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
Copy-Item .env.example .env
ollama pull gpt-oss:20b
ollama pull nomic-embed-text:latest
cd apps/atlas
npm install
cd ..\..
```

If `cargo` is not available on `PATH`, install the Rust stable toolchain before running any Tauri dev or verification command.

Run the desktop app from source:

```powershell
.\scripts\start_atlas_dev.ps1
```

The first launch after a cleanup can take longer because the Tauri/Rust binary may rebuild from scratch.
When the app opens, create or select a user in `Settings` before starting a chat. Atlas starts with no user selected.

## Common Commands

If you open a new terminal later, reactivate the repo environment first:

```powershell
.venv\Scripts\Activate.ps1
```

Start the desktop app:

```powershell
.\scripts\start_atlas_dev.ps1
```

Run only the backend:

```powershell
.venv\Scripts\atlas-backend.exe
```

Open the CLI chat:

```powershell
.venv\Scripts\atlas.exe --user-id your_user
```

Run a single local turn:

```powershell
.venv\Scripts\atlas.exe --user-id your_user --ask "What should I build next?"
```

Repo-local wrappers also work:

```powershell
python atlas.py --user-id your_user
python atlas.py --user-id your_user --ask "What should I build next?"
python -m atlas_local.api
```

## Development

Verify backend tests, the packaged backend resource build, the frontend production bundle, and the Rust desktop shell compile check:

```powershell
.\scripts\verify_repo.ps1
```

That script currently runs:

- Python unit tests under `tests/`
- `npm run build:release` in `apps/atlas`
- `cargo check` in `apps/atlas/src-tauri`

Optional flags:

- `-SkipBackend`
- `-SkipFrontend`

Clean generated artifacts before packaging or before a final push:

```powershell
.\scripts\clean_repo.ps1
```

Optional flags:

- `-IncludeVenv`
- `-IncludeData`

## Repository Layout

- `src/atlas_local`: Python runtime and local API
- `apps/atlas`: desktop shell built with Tauri, React, and Vite
- `prompts`: prompt templates used by the backend
- `scripts`: dev, verify, and cleanup helpers
- `tests`: backend and API test suite

## Git Hygiene

These paths should stay out of Git:

- `.env`
- `.venv`
- `.data`
- `__pycache__`
- `output`
- `apps/atlas/output`
- `apps/atlas/dist`
- `apps/atlas/src-tauri/target`
- `apps/atlas/src-tauri/resources/backend`
- `apps/atlas/src-tauri/resources/prompts`

The repo ignore rules already cover these generated folders.

## Architecture

- `src/atlas_local/api.py`: FastAPI surface for the desktop client
- `src/atlas_local/api_service.py`: backend orchestration and run lifecycle
- `src/atlas_local/run_store.py`: persisted thread and run artifacts
- `src/atlas_local/run_contract.py`: shared run event and trace contract
- `src/atlas_local/graph/*`: agent graph composition and execution
- `src/atlas_local/providers/*`: provider abstraction boundary
- `src/atlas_local/memory/*`: cross-chat memory integration
- `src/atlas_local/world/*`: durable world-state and events
