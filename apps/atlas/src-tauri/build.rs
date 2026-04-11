use std::fs;
use std::path::PathBuf;

fn main() {
    let manifest_dir = PathBuf::from(std::env::var("CARGO_MANIFEST_DIR").expect("CARGO_MANIFEST_DIR"));
    let resources_dir = manifest_dir.join("resources");
    let backend_dir = resources_dir.join("backend");
    let prompts_dir = resources_dir.join("prompts");
    let backend_placeholder = backend_dir.join(".keep");
    let prompts_placeholder = prompts_dir.join(".keep");

    fs::create_dir_all(&backend_dir).expect("failed to create resources/backend");
    fs::create_dir_all(&prompts_dir).expect("failed to create resources/prompts");
    fs::write(&backend_placeholder, b"").expect("failed to create backend placeholder");
    fs::write(&prompts_placeholder, b"").expect("failed to create prompt placeholder");

    tauri_build::build()
}
