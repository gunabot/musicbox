mod decoder;
mod engine;
mod ipc;
mod output;
mod types;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

const DEFAULT_SOCKET: &str = "/tmp/twinpeaks.sock";

fn main() {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    let socket_path = std::env::args()
        .nth(1)
        .unwrap_or_else(|| DEFAULT_SOCKET.to_string());

    let shutdown = Arc::new(AtomicBool::new(false));

    // Block signals in main FIRST, before spawning any threads.
    // All child threads (cpal, decode) inherit the mask, so only our
    // dedicated signal thread will receive SIGINT/SIGTERM.
    let sigset = build_sigset();
    unsafe {
        libc::pthread_sigmask(libc::SIG_BLOCK, &sigset, std::ptr::null_mut());
    }

    let shutdown_sig = Arc::clone(&shutdown);
    std::thread::spawn(move || unsafe {
        let set = build_sigset();
        let mut sig: libc::c_int = 0;
        libc::sigwait(&set, &mut sig);
        log::info!("Received signal {}, shutting down", sig);
        shutdown_sig.store(true, Ordering::Relaxed);
    });

    log::info!("twinpeaks starting on {}", socket_path);

    let mut engine = engine::Engine::new();

    if let Err(e) = ipc::run_server(&socket_path, &mut engine, shutdown) {
        log::error!("Server error: {}", e);
        std::process::exit(1);
    }

    log::info!("twinpeaks exiting");
}

fn build_sigset() -> libc::sigset_t {
    unsafe {
        let mut set: libc::sigset_t = std::mem::zeroed();
        libc::sigemptyset(&mut set);
        libc::sigaddset(&mut set, libc::SIGINT);
        libc::sigaddset(&mut set, libc::SIGTERM);
        set
    }
}
