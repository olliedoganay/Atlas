# Atlas

Atlas is a desktop app for chatting with local Ollama models.

Chats, memories, and run state stay on your machine.

## Scope

- local chat workspace for long-running conversations
- per-user profiles with passwordless or password-protected access
- search across the current chat and all local chats
- automatic and manual context compaction for long threads
- optional cross-chat memory retrieval with manual memory controls
- requires Ollama server running

## Install from Release

For normal Windows use, install the latest release.

1. Open the latest release on GitHub:
   `https://github.com/olliedoganay/Atlas/releases/latest`
2. Download the latest Windows installer or packaged `.exe`.
3. Install and launch `Atlas`.

## Requirements for Source Builds

- Python 3.11+
- Node.js 20+
- Rust stable toolchain with Cargo
- Ollama running locally
- a chat model such as `gpt-oss:20b`
- an embedding model such as `nomic-embed-text:latest`
- Tauri prerequisites for your platform:
  `https://v2.tauri.app/start/prerequisites/`

### Windows source prerequisites

- Windows 10 or 11
- PowerShell

### macOS and Linux source use

- Atlas does not publish macOS or Linux installers.
- macOS and Linux are supported through source builds.
- Use the generic source steps below instead of the Windows-only PowerShell helpers.
- For local secret protection, the machine should have a working OS keychain or secret-store backend.

## Install from Source

### Windows

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

### macOS and Linux

1. Create and activate the Python environment.

```bash
python3 -m venv .venv
source .venv/bin/activate
```

2. Install the Python runtime.

```bash
pip install -r requirements.txt
pip install -e .
```

3. Create the local config file.

```bash
cp .env.example .env
```

4. Pull the local Ollama models.

```bash
ollama pull gpt-oss:20b
ollama pull nomic-embed-text:latest
```

5. Install the desktop dependencies.

```bash
cd apps/atlas
npm install
cd ../..
```

## Run from Source

### Windows

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

### macOS and Linux

Start the desktop shell from source:

```bash
source .venv/bin/activate
cd apps/atlas
npm run tauri dev
```

Optional source commands:

```bash
source .venv/bin/activate
atlas-backend
atlas --user-id your_user
atlas --user-id your_user --ask "What should I build next?"
python -m atlas_local.api
```

Windows helper scripts under `scripts/*.ps1` are Windows-only.

## Security Model

For the threat model and supported protection boundaries, see [SECURITY.md](SECURITY.md).

Atlas is built for local desktop use:

- the desktop app talks to a local backend on the same machine
- Ollama is expected to run locally
- saved runs and profile keys are protected with local OS secret storage
- runtime SQLite and local vector-store storage use encrypted local storage when SQLCipher support is available
- password-protected profiles add an extra unlock step inside Atlas

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

If Atlas only stays open while the terminal that launched it stays open, you are running the source build in dev mode. The Windows release runs as a normal installed desktop app.
