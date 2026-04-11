use std::{
    fs,
    env,
    net::TcpListener,
    path::{Path, PathBuf},
    process::{Child, Command, Stdio},
    sync::Mutex,
    time::{SystemTime, UNIX_EPOCH},
};

use serde::Serialize;
use tauri::{AppHandle, Manager, RunEvent, State};

#[cfg(windows)]
use std::os::windows::process::CommandExt;

const BACKEND_HOST: &str = "127.0.0.1";
const CREATE_NO_WINDOW: u32 = 0x08000000;

#[derive(Clone, Serialize)]
struct BackendRuntime {
    host: String,
    port: u16,
    token: String,
}

#[derive(Default)]
struct BackendState {
    child: Mutex<Option<Child>>,
    runtime: Mutex<Option<BackendRuntime>>,
}

#[tauri::command]
fn restart_backend(app: AppHandle, state: State<'_, BackendState>) -> Result<(), String> {
    stop_backend(&state)?;
    start_backend(app, &state)
}

#[tauri::command]
fn backend_runtime(state: State<'_, BackendState>) -> Result<BackendRuntime, String> {
    let guard = state
        .runtime
        .lock()
        .map_err(|_| "Backend runtime lock is poisoned.".to_string())?;
    guard
        .clone()
        .ok_or_else(|| "Atlas backend runtime is not available.".to_string())
}

pub fn run() {
    tauri::Builder::default()
        .manage(BackendState::default())
        .plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
            if let Some(window) = app.get_webview_window("main") {
                let _ = window.show();
                let _ = window.unminimize();
                let _ = window.set_focus();
            }
        }))
        .setup(|app| {
            start_backend(app.handle().clone(), &app.state::<BackendState>())?;
            Ok(())
        })
        .invoke_handler(tauri::generate_handler![restart_backend, backend_runtime])
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app, event| match event {
            RunEvent::ExitRequested { .. } | RunEvent::Exit => {
                let state = app.state::<BackendState>();
                let _ = stop_backend(&state);
            }
            _ => {}
        });
}

fn start_backend(app: AppHandle, state: &State<'_, BackendState>) -> Result<(), String> {
    let mut guard = state
        .child
        .lock()
        .map_err(|_| "Backend lock is poisoned.".to_string())?;

    if let Some(child) = guard.as_mut() {
        if child
            .try_wait()
            .map_err(|error| error.to_string())?
            .is_none()
        {
            return Ok(());
        }
        *guard = None;
    }

    let repo_root = repo_root()?;
    let runtime = BackendRuntime {
        host: BACKEND_HOST.to_string(),
        port: reserve_port()?,
        token: generate_instance_token(),
    };
    let (program, args, launch_mode) = backend_command(&app, &repo_root, &runtime)?;
    let mut command = Command::new(program);
    command.args(args).stdin(Stdio::null());

    #[cfg(windows)]
    command.creation_flags(CREATE_NO_WINDOW);

    match launch_mode {
        LaunchMode::Development => {
            let log_dir = repo_root.join(".data").join("logs");
            fs::create_dir_all(&log_dir).map_err(|error| error.to_string())?;
            let (stdout, stderr) = backend_log_streams(&log_dir.join("backend.log"))?;
            command.stdout(stdout).stderr(stderr);
            command
                .current_dir(&repo_root)
                .env("ATLAS_API_HOST", BACKEND_HOST)
                .env("ATLAS_API_PORT", runtime.port.to_string())
                .env("ATLAS_INSTANCE_TOKEN", &runtime.token)
                .env("MEM0_DIR", repo_root.join(".data").join("mem0"));

            if let Some(path) = playwright_browsers_path() {
                command.env("PLAYWRIGHT_BROWSERS_PATH", path);
            }

            let python_path = repo_root.join("src");
            let existing_python_path = env::var("PYTHONPATH").unwrap_or_default();
            let merged_python_path = if existing_python_path.is_empty() {
                python_path.display().to_string()
            } else {
                format!("{};{}", python_path.display(), existing_python_path)
            };
            command.env("PYTHONPATH", merged_python_path);
        }
        LaunchMode::Packaged {
            resource_dir,
            data_dir,
        } => {
            fs::create_dir_all(&data_dir).map_err(|error| error.to_string())?;
            fs::create_dir_all(data_dir.join("langgraph")).map_err(|error| error.to_string())?;
            let (stdout, stderr) = if packaged_backend_logs_enabled() {
                let log_dir = data_dir.join("logs");
                fs::create_dir_all(&log_dir).map_err(|error| error.to_string())?;
                backend_log_streams(&log_dir.join("backend.log"))?
            } else {
                (Stdio::null(), Stdio::null())
            };
            command.stdout(stdout).stderr(stderr);
            command
                .current_dir(&data_dir)
                .env("ATLAS_API_HOST", BACKEND_HOST)
                .env("ATLAS_API_PORT", runtime.port.to_string())
                .env("ATLAS_INSTANCE_TOKEN", &runtime.token)
                .env("ATLAS_PROJECT_ROOT", &resource_dir)
                .env("ATLAS_PROMPT_DIR", resource_dir.join("prompts"))
                .env("ATLAS_DATA_DIR", &data_dir)
                .env("MEM0_DIR", data_dir.join("mem0"))
                .env("QDRANT_PATH", data_dir.join("qdrant"))
                .env(
                    "LANGGRAPH_CHECKPOINT_DB",
                    data_dir.join("langgraph").join("checkpoints.sqlite"),
                )
                .env("WORLD_DB_PATH", data_dir.join("world.sqlite"))
                .env("BROWSER_STORAGE_DIR", data_dir.join("browser_runs"))
                .env("BENCHMARKS_DIR", data_dir.join("benchmarks"))
                .env("EVALS_DIR", data_dir.join("evals"))
                .env("PROPOSALS_DIR", data_dir.join("profiles"))
                .env("MEM0_HISTORY_DB", data_dir.join("mem0_history.sqlite"));

            if let Some(path) = playwright_browsers_path() {
                command.env("PLAYWRIGHT_BROWSERS_PATH", path);
            }
        }
    }

    let child = command.spawn().map_err(|error| error.to_string())?;
    *guard = Some(child);
    let mut runtime_guard = state
        .runtime
        .lock()
        .map_err(|_| "Backend runtime lock is poisoned.".to_string())?;
    *runtime_guard = Some(runtime);
    Ok(())
}

fn stop_backend(state: &State<'_, BackendState>) -> Result<(), String> {
    let mut guard = state
        .child
        .lock()
        .map_err(|_| "Backend lock is poisoned.".to_string())?;

    if let Some(mut child) = guard.take() {
        if child
            .try_wait()
            .map_err(|error| error.to_string())?
            .is_none()
        {
            child.kill().map_err(|error| error.to_string())?;
            let _ = child.wait();
        }
    }
    let mut runtime_guard = state
        .runtime
        .lock()
        .map_err(|_| "Backend runtime lock is poisoned.".to_string())?;
    *runtime_guard = None;
    Ok(())
}

fn backend_command(
    app: &AppHandle,
    repo_root: &Path,
    runtime: &BackendRuntime,
) -> Result<(PathBuf, Vec<String>, LaunchMode), String> {
    if !cfg!(debug_assertions) {
        if let Some((exe, resource_dir)) = packaged_sidecar(app) {
            let data_dir = app
                .path()
                .app_data_dir()
                .map_err(|error| error.to_string())?
                .join("runtime");
            return Ok((
                exe,
                vec![
                    "--host".to_string(),
                    runtime.host.clone(),
                    "--port".to_string(),
                    runtime.port.to_string(),
                ],
                LaunchMode::Packaged {
                    resource_dir,
                    data_dir,
                },
            ));
        }
        return Err("Packaged Atlas backend sidecar was not found.".to_string());
    }

    let python = repo_root.join(".venv").join("Scripts").join("python.exe");
    let program = if python.exists() {
        python
    } else {
        PathBuf::from("python")
    };
    Ok((
        program,
        vec![
            "-m".to_string(),
            "atlas_local.api".to_string(),
            "--host".to_string(),
            runtime.host.clone(),
            "--port".to_string(),
            runtime.port.to_string(),
        ],
        LaunchMode::Development,
    ))
}

fn packaged_sidecar(app: &AppHandle) -> Option<(PathBuf, PathBuf)> {
    let resource_dir = app.path().resource_dir().ok()?;
    for asset_root in [resource_dir.clone(), resource_dir.join("resources")] {
        let sidecar = asset_root.join("backend").join("atlas-backend.exe");
        if sidecar.exists() {
            return Some((sidecar, asset_root));
        }
    }
    None
}

fn repo_root() -> Result<PathBuf, String> {
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir
        .parent()
        .and_then(Path::parent)
        .and_then(Path::parent)
        .map(PathBuf::from)
        .ok_or_else(|| "Failed to resolve repository root for Atlas desktop.".to_string())
}

enum LaunchMode {
    Development,
    Packaged { resource_dir: PathBuf, data_dir: PathBuf },
}

fn reserve_port() -> Result<u16, String> {
    let listener = TcpListener::bind((BACKEND_HOST, 0)).map_err(|error| error.to_string())?;
    let port = listener
        .local_addr()
        .map_err(|error| error.to_string())?
        .port();
    drop(listener);
    Ok(port)
}

fn generate_instance_token() -> String {
    let timestamp = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|duration| duration.as_nanos())
        .unwrap_or_default();
    format!("atlas-{}-{}", std::process::id(), timestamp)
}

fn backend_log_streams(path: &Path) -> Result<(Stdio, Stdio), String> {
    let stdout = fs::OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(true)
        .open(path)
        .map_err(|error| error.to_string())?;
    let stderr = stdout.try_clone().map_err(|error| error.to_string())?;
    Ok((Stdio::from(stdout), Stdio::from(stderr)))
}

fn packaged_backend_logs_enabled() -> bool {
    matches!(
        env::var("ATLAS_ENABLE_PACKAGED_LOGS"),
        Ok(value) if value == "1" || value.eq_ignore_ascii_case("true")
    )
}

fn playwright_browsers_path() -> Option<PathBuf> {
    if let Some(path) = env::var_os("PLAYWRIGHT_BROWSERS_PATH") {
        let resolved = PathBuf::from(path);
        if resolved.exists() {
            return Some(resolved);
        }
    }

    env::var_os("LOCALAPPDATA")
        .map(PathBuf::from)
        .map(|path| path.join("ms-playwright"))
        .filter(|path| path.exists())
}
