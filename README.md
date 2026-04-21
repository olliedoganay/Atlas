# Atlas

Atlas is a local-first desktop app for working with local Ollama models.

It combines a multi-thread chat workspace, profile-scoped memory, run inspection, and a built-in code runner. Atlas-managed state stays local to the machine: chats, thread history, checkpoints, memories, run artifacts, and local vector storage.

## What Atlas Does

- desktop chat workspace for long-running local conversations
- per-user profiles with passwordless or password-protected access
- local chat search across the current thread and other threads for the active profile
- thread rename, duplicate, and branch workflows
- reasoning traces, live token streaming, stop controls, and saved run diagnostics
- automatic and manual context compaction for long threads
- optional cross-chat memory retrieval with manual remember/forget controls
- image and file attachments in the composer
- multiple desktop themes, including CRT, Synthwave, and NASA variants
- one-click code execution for model-generated snippets in isolated run windows

Atlas requires a local Ollama runtime. Docker is optional, but required for server-side code execution.

## Install a Release

For normal Windows usage, install the packaged desktop release instead of running from source.

1. Open the latest release:
   `https://github.com/olliedoganay/Atlas/releases/latest`
2. Download the current Windows installer or packaged `.exe`.
3. Install and launch `Atlas`.

## Work From Source

These steps are for development. They launch Atlas against the current repository checkout. They are not a packaging flow.

### Requirements

- Python 3.11+
- Node.js 20+
- Rust stable toolchain with Cargo
- Ollama running locally
- a local chat model such as `gpt-oss:20b`
- a local embedding model such as `nomic-embed-text:latest`
- Tauri prerequisites for your platform:
  `https://v2.tauri.app/start/prerequisites/`

### Windows Setup

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
pip install -e .
Copy-Item .env.example .env
ollama pull gpt-oss:20b
ollama pull nomic-embed-text:latest
Set-Location apps\atlas
npm install
Set-Location ..\..
```

### macOS and Linux Setup

Atlas does not publish macOS or Linux installers. Use the source workflow instead.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e .
cp .env.example .env
ollama pull gpt-oss:20b
ollama pull nomic-embed-text:latest
cd apps/atlas
npm install
cd ../..
```

## Run Atlas From Source

This starts the desktop app itself. It is the normal developer workflow, not a builder.

### Windows

```powershell
.\scripts\start_atlas_dev.ps1
```

That launcher starts `npm run tauri dev` in `apps/atlas` and runs Atlas against the current repo state.

### macOS and Linux

```bash
source .venv/bin/activate
cd apps/atlas
npm run tauri dev
```

### First Launch

1. Open `Settings`.
2. Create or select a profile.
3. Return to `Workspace`.
4. Pick a model and start the first chat.

### Optional Low-Level Commands

Most contributors can ignore these. They are useful for diagnostics and CLI workflows, not for normal desktop usage.

```powershell
.venv\Scripts\atlas-backend.exe
.venv\Scripts\atlas.exe --user-id your_user
.venv\Scripts\atlas.exe --user-id your_user --ask "Summarize this project in three bullets."
python -m atlas_local.api
```

```bash
source .venv/bin/activate
atlas-backend
atlas --user-id your_user
atlas --user-id your_user --ask "Summarize this project in three bullets."
python -m atlas_local.api
```

- `atlas-backend` or `python -m atlas_local.api` runs only the local API/backend.
- `atlas --user-id your_user` starts the terminal chat CLI.
- `atlas --user-id your_user --ask "..."` runs a single CLI turn.

Windows helper scripts under `scripts/*.ps1` are Windows-only.

## Configuration

Copy `.env.example` to `.env` and adjust it if needed. The main settings are:

| Variable | Purpose | Default |
| --- | --- | --- |
| `OLLAMA_URL` | Local Ollama base URL | `http://127.0.0.1:11434` |
| `CHAT_MODEL` | Default chat model for new threads | `gpt-oss:20b` |
| `CHAT_TEMPERATURE` | Optional explicit default temperature. Leave blank to use the selected model's default behavior. | blank (`Model default`) |
| `EMBED_MODEL` | Embedding model used for memory retrieval | `nomic-embed-text:latest` |
| `QDRANT_PATH` | Local vector-store directory | `.data/qdrant` |
| `MEM0_COLLECTION` | Collection name for persistent memory | `atlas_local_memory` |
| `EMBED_DIM` | Embedding dimension expected by local memory storage | `768` |
| `LANGGRAPH_CHECKPOINT_DB` | SQLite checkpoint path for thread state | `.data/langgraph/checkpoints.sqlite` |
| `MEM0_HISTORY_DB` | SQLite history path for memory records | `.data/mem0_history.sqlite` |
| `MEMORY_TOP_K` | Number of recalled memories to inject into a turn | `5` |

## Code Runner

Every code block in a model response gets a **Run** button next to **Copy**. Clicking it opens a separate Atlas Run window that executes the snippet in an isolated environment and streams the output live. Closing the run window stops the run.

Supported server-side languages include:

- Python
- JavaScript
- TypeScript
- Go
- Rust
- C
- C++
- Java
- Ruby
- PHP
- Bash
- C#
- Kotlin
- Swift
- Perl
- Lua
- R
- Elixir
- Dart

HTML code blocks render in a sandboxed client-side preview and do not require Docker.

Key runner behavior:

- dependencies are installed on demand based on snippet imports
- Python GUI snippets can open a live embedded noVNC view for supported toolkits
- Docker-backed runs use disposable containers with CPU, memory, and PID limits
- if Docker is unavailable, Atlas shows a clear retry path in the run window

## Architecture and Security

For the full threat model and protection boundaries, see [SECURITY.md](SECURITY.md).

Atlas is built as a local desktop system:

- the Tauri desktop shell starts and manages a local backend automatically
- the backend binds to loopback on a random local port instead of a public interface
- the frontend authenticates every request with a per-launch instance token
- the backend rejects unexpected origins unless you explicitly opt into an insecure localhost override for development
- Ollama is expected to run locally on the same machine
- local state is stored under Atlas-managed directories, with additional at-rest protection where the runtime supports it

For source runs, local data is written under `.data/`. For packaged builds, Atlas uses the app data directory for the current user.

## Verify the Repo

On Windows, the canonical verification command is:

```powershell
.\scripts\verify_repo.ps1
```

That script runs:

- version consistency checks
- Python tests under `tests/`
- `npm test` in `apps/atlas`
- `npm run build:release` in `apps/atlas`
- `cargo check` in `apps\atlas\src-tauri`

Optional flags:

- `-SkipBackend`
- `-SkipFrontend`

If you prefer `pytest`, the repo is configured to scope test discovery to `tests/`, so plain `pytest` from the repo root is safe.

Build a Windows release bundle locally:

```powershell
.\scripts\build_atlas_release.ps1
```

Artifacts are written under:

```text
apps\atlas\src-tauri\target\release\bundle\
```

## Repository Layout

- `src/atlas_local`: Python backend, API, graph execution, memory integration, security helpers, and CLI entrypoints
- `apps/atlas`: Tauri, React, and Vite desktop shell
- `prompts`: backend prompt templates
- `scripts`: development, verification, packaging, and cleanup helpers
- `tests`: backend and API tests

## Local Data

For source runs, Atlas writes runtime data under `.data/`:

- `langgraph/checkpoints.sqlite`: thread checkpoint state
- `mem0_history.sqlite`: memory history database
- `qdrant/`: local vector storage for semantic memory
- `runs/`: saved run artifacts and run index

These paths should remain untracked. The repo ignore rules already cover them.

## Troubleshooting

If PowerShell blocks repo scripts, allow them for the current session:

```powershell
Set-ExecutionPolicy -Scope Process Bypass
```

If the desktop app opens but no models appear:

1. Make sure Ollama is running.
2. Make sure the models in `.env` have been pulled locally.
3. Restart Atlas.

If the backend shows offline after a Python code change, fully close and reopen the app. A frontend refresh is not enough for backend changes.

If Atlas only stays open while the terminal that launched it stays open, you are running the source build in dev mode. The packaged Windows release runs as a normal installed desktop app.
