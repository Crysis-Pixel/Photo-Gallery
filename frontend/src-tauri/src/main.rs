// Prevents additional console window on Windows in release, DO NOT REMOVE!!
#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use tauri_plugin_shell::ShellExt;
use tauri_plugin_shell::process::CommandEvent;

fn start_backend(app: &tauri::App) {
    // In Tauri v2, the shell plugin natively supports sidecars.
    // It automatically resolves the correct sidecar executable based on the architecture,
    // and correctly terminates it when the parent process exits.
    
    let sidecar_command = match app.handle().shell().sidecar("photo-gallery-backend") {
        Ok(cmd) => cmd,
        Err(e) => {
            eprintln!("Failed to configure sidecar: {}", e);
            return;
        }
    };
        
    // Forward USERPROFILE so the backend finds the same model cache dirs
    let userprofile = std::env::var("USERPROFILE").unwrap_or_default();
    
    match sidecar_command.env("USERPROFILE", userprofile).spawn() {
        Ok((mut rx, mut child)) => {
            eprintln!("Backend started with pid {}", child.pid());
            
            // Spawn a thread to silently read from the sidecar to prevent its stdout/stderr buffers from filling up
            tauri::async_runtime::spawn(async move {
                while let Some(event) = rx.recv().await {
                    match event {
                        CommandEvent::Stdout(data) => print!("{}", String::from_utf8_lossy(&data)),
                        CommandEvent::Stderr(data) => eprint!("{}", String::from_utf8_lossy(&data)),
                        CommandEvent::Terminated(payload) => {
                            eprintln!("Backend sidecar terminated with code {:?}", payload.code);
                        }
                        _ => {}
                    }
                }
            });
        }
        Err(e) => eprintln!("Failed to spawn backend sidecar: {e}"),
    }
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .setup(|app| {
            start_backend(app);
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}