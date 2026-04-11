# Atlas

Atlas is a desktop app for chatting with local Ollama models.

It keeps chats, memory, and thread state on your machine.

## Current Scope

- chat workspace for long-running local conversations
- search across the current chat and all local chats
- automatic and manual context compaction for long threads
- optional local memory retrieval with manual memory controls

## Stack

- desktop shell: Tauri, React, Vite
- backend: Python, FastAPI, LangGraph
- model runtime: Ollama
- local storage: `.data/`, local Qdrant, sqlite checkpoints

## Requirements

- Windows 10 or 11 with PowerShell
- Python 3.11+
- Node.js 20+
- Rust stable toolchain with Cargo
- Ollama running locally
- a chat model such as `gpt-oss:20b`
- an embedding model such as `nomic-embed-text:latest`

## Platform Notes

The repo scripts, launcher wrappers, verification flow, and packaging steps are Windows-first. The source tree is mostly portable, but the documented commands assume Windows paths, PowerShell, and `.exe` entrypoints.

## Install

1. Create and activate the Python environment.

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

2. Install the Python runtime.

```powershell
pip install -r requirements.txt
pip install -e .
```

3. Create the local config file.

```powershell
Copy-Item .env.example .env
```

4. Pull the local Ollama models.

```powershell
ollama pull gpt-oss:20b
ollama pull nomic-embed-text:latest
```

5. Install the desktop dependencies.

```powershell
Set-Location apps\atlas
npm install
Set-Location ..\..
```

If `cargo` is not available on `PATH`, install the Rust stable toolchain before running any Tauri dev or verification command.

## Run

Start the desktop app from source:

```powershell
.\scripts\start_atlas_dev.ps1
```

On first launch:

1. Open `Settings`
2. Create or select a user
3. Return to `Workspace`
4. Pick a model and start the first chat

## Other Commands

If you open a new terminal later, reactivate the repo environment first:

```powershell
.venv\Scripts\Activate.ps1
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

## Search and Compaction

`Search` lets you search inside the current chat and across all local chats, then jump directly to the matched thread or message.

`Auto compact long chats` summarizes older turns when the represented context gets too large for the active model window.

`Compact now` triggers the same summary flow on demand when you want to shrink prompt pressure before the next turn.

Compaction does not delete visible messages from the chat UI. It changes how older context is represented when Atlas builds the next model prompt.

## Memory Model

Atlas keeps memory simple:

- manual notes can be added or deleted in `Settings`
- semantic retrieval can pull relevant memories from other chats for the same user
- lightweight heuristic extraction persists durable user facts from chat into memory
- extracted memory is intentionally limited to profile, preference, and constraint-style notes

## Verify the Repo

Run the repo verification script:

```powershell
.\scripts\verify_repo.ps1
```

That script currently runs:

- Python unit tests under `tests/`
- `npm run build:release` in `apps/atlas`
- `cargo check` in `apps/atlas\src-tauri`

Optional flags:

- `-SkipBackend`
- `-SkipFrontend`

## Clean Generated Artifacts

```powershell
.\scripts\clean_repo.ps1
```

Optional flags:

- `-IncludeVenv`
- `-IncludeData`

## Repository Layout

- `src/atlas_local`: Python runtime, API, graph execution, memory integration, and CLI entrypoints
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

## Privacy Notes

Atlas is designed for local use:

- the desktop app talks to a local backend
- Ollama is expected to run on the same machine
- thread history, summaries, and memory stay on disk locally

Current limitation:

- local data is persisted on disk but not encrypted at rest

That means Atlas is local-first, but not yet a hardened encrypted vault.

## Architecture

- `src/atlas_local/api.py`: FastAPI surface for the desktop client
- `src/atlas_local/api_service.py`: backend orchestration, streaming, search, compaction, duplication, and reset flows
- `src/atlas_local/run_store.py`: persisted thread and run artifacts
- `src/atlas_local/run_contract.py`: shared run event and trace contract
- `src/atlas_local/graph/*`: chat graph composition, context compaction, and memory injection
- `src/atlas_local/memory/*`: Mem0 integration and heuristic memory extraction

## Troubleshooting

If PowerShell blocks repo scripts, run them in the current session with:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

If the desktop app opens but no models appear:

1. Make sure Ollama is running
2. Make sure the models in `.env` have been pulled locally
3. Restart Atlas from the desktop shell

If the backend is offline after a code change, fully close and reopen the app. Backend Python changes require a real restart, not only a frontend refresh.
