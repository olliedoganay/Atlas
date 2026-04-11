# Atlas

Atlas is a Windows desktop app for chatting with local Ollama models.

Chats, memories, and run state stay on your machine.

## Scope

- local chat workspace for long-running conversations
- per-user profiles with passwordless or password-protected access
- search across the current chat and all local chats
- automatic and manual context compaction for long threads
- optional cross-chat memory retrieval with manual memory controls

## Install from Release

For normal use, install a packaged release instead of running the repo in dev mode.

1. Open the repository `Releases` page on GitHub.
2. Download the latest Windows installer or packaged `.exe`.
3. Install and launch `Atlas`.

The packaged app runs without the extra PowerShell window used by `tauri dev`.

## Requirements for Source Builds

- Windows 10 or 11
- PowerShell
- Python 3.11+
- Node.js 20+
- Rust stable toolchain with Cargo
- Ollama running locally
- a chat model such as `gpt-oss:20b`
- an embedding model such as `nomic-embed-text:latest`

## Install from Source

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

## Run from Source

Start the desktop app from source:

```powershell
.\scripts\start_atlas_dev.ps1
```

On first launch:

1. Open `Settings`
2. Create or select a user
3. Return to `Workspace`
4. Pick a model and start the first chat

If you open a new terminal later, reactivate the repo environment first:

```powershell
.venv\Scripts\Activate.ps1
```

Optional source commands:

```powershell
.venv\Scripts\atlas-backend.exe
.venv\Scripts\atlas.exe --user-id your_user
.venv\Scripts\atlas.exe --user-id your_user --ask "What should I build next?"
python -m atlas_local.api
```

## Security Model

Atlas is designed for local use:

- the desktop app talks to a local backend
- Ollama is expected to run on the same machine
- Windows builds protect the run index and saved run artifacts with DPAPI
- LangGraph checkpoints, Mem0 history, and local Qdrant storage are encrypted at rest with SQLCipher-backed local storage
- password-protected profiles wrap their profile key behind the profile password
- packaged backend logs stay off by default unless you explicitly enable them

## Verify the Repo

Run the repo verification script:

```powershell
.\scripts\verify_repo.ps1
```

That script runs:

- Python unit tests under `tests/`
- `npm run build:release` in `apps/atlas`
- `cargo check` in `apps\atlas\src-tauri`

Optional flags:

- `-SkipBackend`
- `-SkipFrontend`

Build a Windows release bundle locally:

```powershell
.\scripts\build_atlas_release.ps1
```

That writes installer artifacts under:

```text
apps\atlas\src-tauri\target\release\bundle\
```

## Repository Layout

- `src/atlas_local`: Python runtime, API, graph execution, memory integration, security helpers, and CLI entrypoints
- `apps/atlas`: Tauri, React, and Vite desktop shell
- `prompts`: backend prompt templates
- `scripts`: dev, verify, package, and cleanup helpers
- `tests`: backend and API test suite

## Local Data

Atlas writes runtime data under `.data/`:

- `langgraph/checkpoints.sqlite`: thread checkpoint state
- `mem0_history.sqlite`: Mem0 history database
- `qdrant/`: local vector storage for semantic memory
- `runs/`: saved run artifacts and run index

These paths should stay out of Git. The repo ignore rules already cover them.

## Troubleshooting

If PowerShell blocks repo scripts, run them in the current session with:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

If the desktop app opens but no models appear:

1. Make sure Ollama is running.
2. Make sure the models in `.env` have been pulled locally.
3. Restart Atlas.

If the backend is offline after a code change, fully close and reopen the app. Backend Python changes require a real restart, not only a frontend refresh.

If Atlas only works while a PowerShell window stays open, you are running the source/dev launcher. Use a packaged build from GitHub Releases for normal desktop use.
