# Security

## Deployment model

Atlas is a local desktop application.

- Windows is the packaged release target.
- macOS and Linux are supported through source builds.

Across supported local setups:

- the Tauri shell starts a backend on `127.0.0.1`
- the shell and backend authenticate with an instance token
- Ollama is expected to run on the same machine
- packaged backend logs stay off by default

## Storage protection

Atlas protects local data in two layers:

- saved runs, profile keys, and related secrets use local OS secret storage
- runtime SQLite files and local vector-store storage use encrypted local storage when SQLCipher support is available

On Windows, local secret storage uses DPAPI. On macOS and Linux source builds, Atlas uses the local OS keychain or secret store when available.

Password-protected profiles add a separate unlock step inside Atlas. Passwordless profiles still remain scoped to the local machine and local user account.

## What this is meant to protect against

- accidental exposure through another local process or browser page that does not have the backend instance token
- casual inspection of saved run files on disk
- opening a password-protected profile inside Atlas without the profile password

## What this does not try to protect against

- malware or any other process already running as the same local user
- a machine that is already compromised
- data sent to a remote model endpoint if you point Atlas away from a local Ollama service
- development overrides that you enable intentionally

## Development override

Atlas includes one explicit local development override:

- `ATLAS_ALLOW_INSECURE_LOCALHOST=1`

This is for development only. Packaged builds refuse to start if that override is enabled.

## Reporting

If you find a security issue, report it privately with:

- affected version
- Windows version
- exact reproduction steps
- whether it affects a packaged build, a source build, or both
