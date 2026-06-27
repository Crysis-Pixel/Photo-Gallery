// Prevents additional console window on Windows in release, DO NOT REMOVE!!
// Force rebuild trigger to embed new icons
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::sync::Mutex;
use tauri::Manager;
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandChild;
#[cfg(not(debug_assertions))]
use tauri_plugin_shell::process::CommandEvent;

struct SidecarState {
    child: Mutex<Option<CommandChild>>,
    pid:   Mutex<Option<u32>>,
}

/// Kill a process and its entire tree using `taskkill /F /T /PID`.
/// Falls back to the Tauri `CommandChild::kill()` if taskkill fails.
fn kill_tree(pid: u32, child: CommandChild) {
    let killed = std::process::Command::new("taskkill")
        .args(["/F", "/T", "/PID", &pid.to_string()])
        .output();

    match killed {
        Ok(out) if out.status.success() => {
            eprintln!("Backend process tree (pid {pid}) killed via taskkill");
        }
        Ok(out) => {
            eprintln!(
                "taskkill exited non-zero: {}",
                String::from_utf8_lossy(&out.stderr)
            );
            let _ = child.kill();
        }
        Err(e) => {
            eprintln!("taskkill failed ({e}), falling back to child.kill()");
            let _ = child.kill();
        }
    }
}

fn start_backend(app: &tauri::App) -> Option<(CommandChild, u32)> {
    // In debug/dev builds, the Python backend is managed externally (by concurrently).
    // Only spawn the sidecar in production release builds.
    #[cfg(debug_assertions)]
    {
        let _ = app; // avoid unused parameter warning
        eprintln!("Debug build: skipping sidecar — expecting external backend at 127.0.0.1:8000");
        None
    }

    #[cfg(not(debug_assertions))]
    {
        let sidecar_command = match app.handle().shell().sidecar("photo-gallery-backend") {
            Ok(cmd) => cmd,
            Err(e) => {
                eprintln!("Failed to configure sidecar: {}", e);
                return None;
            }
        };

        // Forward all user-profile env vars so the backend resolves model
        // cache dirs correctly regardless of how the sidecar is launched.
        let userprofile  = std::env::var("USERPROFILE").unwrap_or_default();
        let appdata      = std::env::var("APPDATA").unwrap_or_default();
        let localappdata = std::env::var("LOCALAPPDATA").unwrap_or_default();

        // Derive the same paths that runtime_env.py would compute
        let insightface_home = format!("{}\\.insightface", userprofile);
        let hf_home          = format!("{}\\.cache\\huggingface", userprofile);
        let torch_home       = format!("{}\\.cache\\torch", userprofile);
        let clip_cache       = format!("{}\\.cache\\clip", userprofile);

        // Forward DATABASE_URL if present so the sidecar uses PostgreSQL in dev.
        let database_url = std::env::var("DATABASE_URL").unwrap_or_default();

        match sidecar_command
            .env("USERPROFILE",          &userprofile)
            .env("APPDATA",              &appdata)
            .env("LOCALAPPDATA",         &localappdata)
            .env("INSIGHTFACE_HOME",     &insightface_home)
            .env("HF_HOME",              &hf_home)
            .env("HUGGINGFACE_HUB_CACHE", format!("{}\\hub", hf_home))
            .env("TRANSFORMERS_CACHE",   format!("{}\\hub", hf_home))
            .env("TORCH_HOME",           &torch_home)
            .env("CLIP_CACHE",           &clip_cache)
            .env("DATABASE_URL",         &database_url)
            .spawn() {
            Ok((mut rx, child)) => {
                let pid = child.pid();
                eprintln!("Backend started with pid {pid}");

                // Drain stdout/stderr so the sidecar buffers never fill up
                tauri::async_runtime::spawn(async move {
                    while let Some(event) = rx.recv().await {
                        match event {
                            CommandEvent::Stdout(data) => {
                                print!("{}", String::from_utf8_lossy(&data))
                            }
                            CommandEvent::Stderr(data) => {
                                eprint!("{}", String::from_utf8_lossy(&data))
                            }
                            CommandEvent::Terminated(payload) => {
                                eprintln!(
                                    "Backend sidecar terminated with code {:?}",
                                    payload.code
                                );
                            }
                            _ => {}
                        }
                    }
                });

                Some((child, pid))
            }
            Err(e) => {
                eprintln!("Failed to spawn backend sidecar: {e}");
                None
            }
        }
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .plugin(tauri_plugin_dialog::init())
        .manage(SidecarState {
            child: Mutex::new(None),
            pid:   Mutex::new(None),
        })
        .setup(|app| {
            if let Some((child, pid)) = start_backend(app) {
                let state = app.state::<SidecarState>();
                *state.child.lock().unwrap() = Some(child);
                *state.pid.lock().unwrap()   = Some(pid);
            }
            Ok(())
        })
        .build(tauri::generate_context!())
        .expect("error while building tauri application")
        .run(|app_handle, event| {
            if let tauri::RunEvent::Exit | tauri::RunEvent::ExitRequested { .. } = event {
                let state = app_handle.state::<SidecarState>();
                let child = state.child.lock().unwrap().take();
                let pid   = state.pid.lock().unwrap().take();

                if let Some(child) = child {
                    if let Some(pid) = pid {
                        kill_tree(pid, child);
                    } else {
                        let _ = child.kill();
                    }
                }
            }
        });
}