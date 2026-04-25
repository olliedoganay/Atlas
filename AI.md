# Atlas Repo Guide

## Snapshot

- Verified on 2026-04-23 on this machine with `.\scripts\verify_repo.ps1`.
- Baseline at that point:
  - Python backend tests: 104 passed
  - Frontend tests: 21 passed
  - Frontend production build: passed
  - Backend PyInstaller build: passed
  - `cargo check`: passed
- Atlas is a local-first desktop app: Tauri shell + React frontend + Python FastAPI backend + Ollama + local encrypted storage.

## Top-Level Map

- `apps/atlas`
  - React 19 + Vite desktop UI.
- `apps/atlas/src-tauri`
  - Rust Tauri shell that launches and owns the backend process.
- `src/atlas_local`
  - Python backend, API, chat orchestration, memory, storage, code runner.
- `prompts`
  - Prompt templates used by the backend.
- `tests`
  - Python test suite.
- `scripts`
  - Dev, build, and repo verification helpers.
- `.data`
  - Source-run local state and artifacts.

## Startup Flow

1. `.\scripts\start_atlas_dev.ps1`
2. `apps/atlas/src-tauri/src/lib.rs`
   - starts the backend on `127.0.0.1` with a random port
   - generates `ATLAS_INSTANCE_TOKEN`
   - exposes the runtime to the frontend through Tauri commands
3. `apps/atlas/src/lib/api.ts`
   - asks Tauri for backend runtime info
   - sends authenticated HTTP requests to the Python backend
4. `src/atlas_local/api.py`
   - FastAPI app, REST endpoints, streaming endpoints, request auth/origin checks
5. `src/atlas_local/api_service.py`
   - run queue, chat lifecycle, thread history, compaction, memory, users, discovery

## Backend Navigation

- `src/atlas_local/config.py`
  - resolves `.env`, project/data paths, model defaults.
- `src/atlas_local/api.py`
  - API surface for health, status, models, discovery, threads, chat, runner, admin resets.
- `src/atlas_local/api_service.py`
  - main backend brain.
  - good first file for anything involving runs, threads, history, streaming, compaction, or search.
- `src/atlas_local/graph/builder.py`
  - LangGraph wiring.
  - current graph sequence is `retrieve_memories -> synthesize_answer -> extract_updates -> persist`.
- `src/atlas_local/graph/nodes.py`
  - memory retrieval, prompt assembly, answer generation, memory extraction/persistence.
- `src/atlas_local/llm.py`
  - Ollama integration, local model inspection, reasoning capability detection, context window lookup.
- `src/atlas_local/run_store.py`
  - local thread/run/user index plus encrypted run artifacts.
- `src/atlas_local/security.py`
  - DPAPI/keyring handling and SQLCipher-backed SQLite setup.
- `src/atlas_local/memory/mem0_service.py`
  - Mem0 + local Qdrant wiring.
- `src/atlas_local/code_runner.py`
  - Docker-backed language execution and client/server language split.
- `src/atlas_local/cli.py`
  - CLI entrypoint for `atlas ask`, `atlas chat`, and `atlas memories`.

## Frontend Navigation

- `apps/atlas/src/App.tsx`
  - route table.
- `apps/atlas/src/components/AtlasShell.tsx`
  - global nav, chat list, startup shell behavior, backend restart.
- `apps/atlas/src/pages/WorkspacePage.tsx`
  - main chat UI.
  - model locking, reasoning mode, attachments, history, runs, compaction UX all converge here.
- `apps/atlas/src/components/RunStreamCoordinator.tsx`
  - subscribes to chat stream events and keeps React Query/Zustand in sync.
- `apps/atlas/src/store/useAtlasStore.ts`
  - persistent UI state and live run state.
- `apps/atlas/src/lib/api.ts`
  - typed frontend API client and Tauri backend-runtime bridge.
- `apps/atlas/src/lib/startupState.ts`
  - gating logic for startup, profile lock state, Ollama availability, and model readiness.
- `apps/atlas/src/pages/SettingsPage.tsx`
  - users, profile locking/unlocking, manual memories, resets, themes.
- `apps/atlas/src/pages/AdvancedPage.tsx`
  - runtime health and recent run diagnostics.
- `apps/atlas/src/pages/CodeRunnerPage.tsx`
  - separate run window for snippet execution.

## Current In-Flight Work

The current staged worktree is mostly a Discovery feature:

- backend
  - `src/atlas_local/discovery.py`
  - `/discovery` route added in `src/atlas_local/api.py`
  - `AtlasBackendService.discovery()` added in `src/atlas_local/api_service.py`
- frontend
  - `apps/atlas/src/pages/DiscoveryPage.tsx`
  - route + nav wiring in `apps/atlas/src/App.tsx` and `apps/atlas/src/components/AtlasShell.tsx`
  - helper formatting in `apps/atlas/src/lib/discoveryUi.ts`
  - styling in `apps/atlas/src/styles.css`
  - API types + request in `apps/atlas/src/lib/api.ts`
- tests
  - `tests/test_discovery.py`
  - `tests/test_api.py`
  - `apps/atlas/src/lib/discoveryUi.test.ts`
- docs
  - `README.md`

## Useful Commands

- Full verification:
  - `.\scripts\verify_repo.ps1`
- Start desktop app from source:
  - `.\scripts\start_atlas_dev.ps1`
- Backend only:
  - `python -m atlas_local.api`
- Backend tests:
  - `python -m unittest discover -s tests -p "test_*.py"`
  - `pytest`
- Frontend tests:
  - `cd apps\atlas`
  - `npm test`
- Frontend release build:
  - `cd apps\atlas`
  - `npm run build:release`
- Rust shell check:
  - `cd apps\atlas\src-tauri`
  - `cargo check`

## Where To Start By Task

- Backend does not boot or frontend cannot connect:
  - `apps/atlas/src-tauri/src/lib.rs`
  - `apps/atlas/src/lib/api.ts`
  - `src/atlas_local/api.py`
- Chat behavior, streaming, compaction, or run history:
  - `src/atlas_local/api_service.py`
  - `src/atlas_local/graph/nodes.py`
  - `apps/atlas/src/pages/WorkspacePage.tsx`
  - `apps/atlas/src/components/RunStreamCoordinator.tsx`
- Profiles, encryption, or local storage:
  - `src/atlas_local/run_store.py`
  - `src/atlas_local/security.py`
  - `apps/atlas/src/pages/SettingsPage.tsx`
- Model inventory or discovery recommendations:
  - `src/atlas_local/discovery.py`
  - `src/atlas_local/llm.py`
  - `apps/atlas/src/pages/DiscoveryPage.tsx`
  - `apps/atlas/src/lib/discoveryUi.ts`
- Code execution:
  - `src/atlas_local/code_runner.py`
  - `apps/atlas/src/pages/CodeRunnerPage.tsx`

## Constraints To Remember

- Source runs write local state under `.data`.
- Full app behavior still depends on a local Ollama runtime.
- Docker is optional for chat, but required for server-side code execution.
- The worktree already contains staged user changes. Do not revert or overwrite them casually.
