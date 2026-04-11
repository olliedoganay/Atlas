# Atlas

Atlas is a local-first desktop chat workspace for Ollama. It runs a Tauri desktop shell on top of a Python backend, keeps thread history on your machine, and locks each thread to its chosen model and temperature after the first message.

## Current Scope

- chat-only local runtime
- optional cross-chat memory backed by Mem0 + local Qdrant storage
- manual memory add/delete from the desktop settings page
- persisted thread history, run events, and stream state on disk

## Stack

- desktop shell: Tauri, React, Vite
- backend: Python, FastAPI, LangGraph
- model runtime: Ollama
- local storage: `.data/`, local Qdrant, sqlite checkpoints

## Requirements

- Windows 10/11 with PowerShell
- Python 3.11+
- Node.js 20+
- Rust stable toolchain with Cargo
- Ollama running locally
- a chat model such as `gpt-oss:20b`
- an embedding model such as `nomic-embed-text:latest`

## Platform Notes

The repo scripts, CI, launcher wrappers, and packaging flow are Windows-first. The source tree is mostly portable, but the documented commands and automated verification assume Windows paths, PowerShell, and `.exe` entrypoints.

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

On first launch, pick or create a user in `Settings` before starting a chat. Atlas starts with no active user selected.

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

## Memory Model

Atlas currently keeps memory simple:

- manual notes can be added or deleted in `Settings`
- semantic retrieval can pull relevant memories from other chats for the same user
- lightweight heuristic extraction persists durable user facts from chat into memory
- extracted memory is intentionally limited to profile, preference, and constraint-style notes

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

- `src/atlas_local`: Python runtime, API, graph execution, memory integration, and launchers
- `apps/atlas`: desktop shell built with Tauri, React, and Vite
- `prompts`: prompt templates used by the backend
- `scripts`: dev, verify, package, and cleanup helpers
- `tests`: backend and API test suite

## Local Data

Atlas writes runtime data under `.data/`:

- `langgraph/checkpoints.sqlite`: thread checkpoint state
- `mem0_history.sqlite`: Mem0 history database
- `qdrant/`: local vector storage for semantic memory
- `runs/`: saved run artifacts and event streams

These paths should stay out of Git. The repo ignore rules already cover them.

## Architecture

- `src/atlas_local/api.py`: FastAPI surface for the desktop client
- `src/atlas_local/api_service.py`: backend orchestration, streaming, thread duplication, and reset flows
- `src/atlas_local/run_store.py`: persisted thread and run artifacts
- `src/atlas_local/run_contract.py`: shared run event and trace contract
- `src/atlas_local/graph/*`: chat graph composition, context compaction, and memory injection
- `src/atlas_local/memory/*`: Mem0 integration and heuristic memory extraction
- `src/atlas_local/providers/*`: provider abstraction boundary
