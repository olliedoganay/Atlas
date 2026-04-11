# Security

## Supported model

Atlas is designed as a local Windows desktop app.

- the desktop shell starts a local backend on `127.0.0.1`
- the shell and backend authenticate with an instance token
- local packaged builds keep backend logs off by default
- saved run artifacts and the run index are protected with Windows DPAPI
- packaged Windows runtimes use SQLCipher-backed local storage for local SQLite state and local Qdrant persistence
- password-protected profiles require the profile password before Atlas can unlock that profile's data key

## What Atlas is intended to protect against

- accidental exposure through a local browser page or another process hitting the backend without the instance token
- casual access to saved run artifacts on disk
- access to a password-protected profile from inside Atlas without the profile password

## What Atlas does not claim to protect against

- malware or another process already running as the same Windows user with access to your session
- a machine that is already fully compromised
- data sent to a remote model endpoint if you change the Ollama/base URL away from a local service
- development overrides that you explicitly enable on purpose

## Development overrides

The backend has an explicit local development override:

- `ATLAS_ALLOW_INSECURE_LOCALHOST=1`

This is for development only. Packaged Atlas builds reject startup if that override is enabled.

## Data locations

Packaged Atlas stores runtime data under the app data runtime directory. Source/dev runs store runtime data under the repo-local `.data/` directory.

Typical local data includes:

- LangGraph checkpoints
- Mem0 history
- local Qdrant storage
- saved runs and the run index

These paths should never be committed to Git.

## Reporting

If you find a security issue, open a private report with enough detail to reproduce it safely:

- affected version
- Windows version
- exact steps
- whether the issue affects packaged builds, source/dev builds, or both
