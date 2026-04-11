# Atlas Desktop Shell

This folder contains the Tauri, React, and Vite frontend for Atlas.

For normal development, start the app from the repo root so the desktop shell and Python backend boot together:

```powershell
.\scripts\start_atlas_dev.ps1
```

If you need to work inside this folder directly:

```powershell
npm run dev
npm run build
npm run tauri dev
```

Generated folders such as `dist`, `output`, and `src-tauri/target` are ignored and should not be committed.

## Recommended IDE Setup

- [VS Code](https://code.visualstudio.com/)
- [Tauri VS Code extension](https://marketplace.visualstudio.com/items?itemName=tauri-apps.tauri-vscode)
- [rust-analyzer](https://marketplace.visualstudio.com/items?itemName=rust-lang.rust-analyzer)
