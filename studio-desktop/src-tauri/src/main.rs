// Copyright 2026 Firefly Software Solutions Inc
//
// Licensed under the Apache License, Version 2.0

//! Firefly Studio desktop app — Tauri entry point.
//!
//! Manages the lifecycle of the Python sidecar process:
//! 1. Find a free port
//! 2. Spawn the PyInstaller-bundled Studio server
//! 3. Wait for `/api/health` to respond
//! 4. Navigate the webview to the local server
//! 5. Kill the sidecar on exit

#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use std::net::TcpListener;
use std::process::{Child, Stdio};
use std::sync::Mutex;
use std::time::{Duration, Instant};

use tauri::Manager;

/// Global handle to the sidecar process so we can kill it on exit.
struct SidecarState(Mutex<Option<Child>>);

/// Find a free TCP port by binding to port 0.
fn find_free_port() -> u16 {
    let listener = TcpListener::bind("127.0.0.1:0").expect("Failed to bind to ephemeral port");
    listener.local_addr().unwrap().port()
}

/// Resolve the path to the sidecar binary.
///
/// In development, looks for the binary relative to the executable.
/// In production (bundled), looks in the Tauri resources directory.
fn find_sidecar(app: &tauri::AppHandle) -> std::path::PathBuf {
    // Try Tauri resource directory first (bundled app)
    if let Ok(resource_dir) = app.path().resource_dir() {
        let sidecar = resource_dir.join("sidecar").join(sidecar_name());
        if sidecar.exists() {
            eprintln!("[studio] Found sidecar at: {}", sidecar.display());
            return sidecar;
        }
        eprintln!(
            "[studio] Sidecar not found at: {} (trying fallback)",
            sidecar.display()
        );
    }

    // Fall back to looking next to the executable (dev mode)
    let exe_dir = std::env::current_exe()
        .expect("Failed to get executable path")
        .parent()
        .unwrap()
        .to_path_buf();

    let sidecar = exe_dir.join(sidecar_name());
    eprintln!("[studio] Fallback sidecar path: {}", sidecar.display());
    sidecar
}

/// Platform-specific sidecar binary name.
fn sidecar_name() -> &'static str {
    if cfg!(target_os = "windows") {
        "firefly-studio.exe"
    } else {
        "firefly-studio"
    }
}

/// Poll the health endpoint until it responds or timeout is reached.
async fn wait_for_health(port: u16, timeout: Duration) -> Result<(), String> {
    let url = format!("http://127.0.0.1:{port}/api/health");
    let client = reqwest::Client::builder()
        .timeout(Duration::from_secs(2))
        .build()
        .map_err(|e| format!("Failed to create HTTP client: {e}"))?;

    let start = Instant::now();
    let mut attempt = 0u32;

    while start.elapsed() < timeout {
        attempt += 1;
        match client.get(&url).send().await {
            Ok(resp) if resp.status().is_success() => {
                eprintln!(
                    "[studio] Health check passed after {attempt} attempts ({:.1}s)",
                    start.elapsed().as_secs_f64()
                );
                return Ok(());
            }
            Ok(resp) => {
                eprintln!(
                    "[studio] Health check attempt {attempt}: status {}",
                    resp.status()
                );
            }
            Err(e) => {
                if attempt <= 3 || attempt % 10 == 0 {
                    eprintln!("[studio] Health check attempt {attempt}: {e}");
                }
            }
        }
        tokio::time::sleep(Duration::from_millis(500)).await;
    }

    Err(format!(
        "Sidecar did not become healthy within {}s ({attempt} attempts)",
        timeout.as_secs()
    ))
}

fn main() {
    tauri::Builder::default()
        .plugin(tauri_plugin_shell::init())
        .manage(SidecarState(Mutex::new(None)))
        .setup(|app| {
            let port = find_free_port();
            let sidecar_path = find_sidecar(&app.handle());

            eprintln!("[studio] Starting sidecar on port {port}...");
            eprintln!("[studio] Sidecar path: {}", sidecar_path.display());

            // Spawn the sidecar process with stderr piped for debugging
            let child = std::process::Command::new(&sidecar_path)
                .args([
                    "--port",
                    &port.to_string(),
                    "--host",
                    "127.0.0.1",
                    "--no-browser",
                ])
                .stdout(Stdio::inherit())
                .stderr(Stdio::inherit())
                .spawn()
                .map_err(|e| {
                    let msg = format!(
                        "Failed to start sidecar at {}: {e}",
                        sidecar_path.display()
                    );
                    eprintln!("[studio] {msg}");
                    msg
                })?;

            eprintln!("[studio] Sidecar spawned (PID: {})", child.id());

            // Store the child handle for cleanup
            let state = app.state::<SidecarState>();
            *state.0.lock().unwrap() = Some(child);

            // Wait for health and navigate in a background task
            let handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                match wait_for_health(port, Duration::from_secs(30)).await {
                    Ok(()) => {
                        let url = format!("http://127.0.0.1:{port}");
                        eprintln!("[studio] Navigating to {url}");
                        if let Some(window) = handle.get_webview_window("main") {
                            let _ = window.navigate(url.parse().unwrap());
                        }
                    }
                    Err(e) => {
                        eprintln!("[studio] {e}");
                    }
                }
            });

            Ok(())
        })
        .on_window_event(|window, event| {
            if let tauri::WindowEvent::Destroyed = event {
                // Kill the sidecar when the window is destroyed
                let child = window.state::<SidecarState>().0.lock().unwrap().take();
                if let Some(mut child) = child {
                    eprintln!("[studio] Killing sidecar (PID: {})", child.id());
                    let _ = child.kill();
                    let _ = child.wait();
                }
            }
        })
        .run(tauri::generate_context!())
        .expect("Error while running Firefly Studio");
}
