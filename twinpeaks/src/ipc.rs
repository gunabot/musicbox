use std::io::{BufRead, BufReader, Read, Write};
use std::os::fd::AsRawFd;
use std::os::unix::net::{UnixListener, UnixStream};
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

use anyhow::{Context, Result};

use crate::engine::Engine;
use crate::types::{Command, Response};

const MAX_CMD_LEN: u64 = 8192;
const ACCEPT_POLL_TIMEOUT_MS: i32 = 500;

pub fn run_server(socket_path: &str, engine: &mut Engine, shutdown: Arc<AtomicBool>) -> Result<()> {
    cleanup_stale_socket(socket_path);

    let listener =
        UnixListener::bind(socket_path).with_context(|| format!("Cannot bind {}", socket_path))?;
    listener
        .set_nonblocking(true)
        .context("Failed to set non-blocking")?;

    log::info!("Listening on {}", socket_path);

    while !shutdown.load(Ordering::Relaxed) {
        match wait_for_connection(&listener) {
            Ok(true) => match listener.accept() {
                Ok((stream, _)) => {
                    if let Err(e) = handle_connection(stream, engine, &shutdown) {
                        log::warn!("Connection error: {}", e);
                    }
                }
                Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {}
                Err(e) => {
                    log::error!("Accept error: {}", e);
                }
            },
            Ok(false) => {}
            Err(e) => log::error!("Listener poll error: {}", e),
        }
    }

    std::fs::remove_file(socket_path).ok();
    log::info!("Server shut down");
    Ok(())
}

fn wait_for_connection(listener: &UnixListener) -> Result<bool> {
    let mut fds = libc::pollfd {
        fd: listener.as_raw_fd(),
        events: libc::POLLIN,
        revents: 0,
    };

    let rc = unsafe { libc::poll(&mut fds as *mut libc::pollfd, 1, ACCEPT_POLL_TIMEOUT_MS) };

    if rc < 0 {
        let err = std::io::Error::last_os_error();
        if err.kind() == std::io::ErrorKind::Interrupted {
            return Ok(false);
        }
        return Err(err.into());
    }

    if rc == 0 {
        return Ok(false);
    }

    if (fds.revents & (libc::POLLERR | libc::POLLHUP | libc::POLLNVAL)) != 0 {
        anyhow::bail!("poll() returned revents={:#x}", fds.revents);
    }

    Ok((fds.revents & libc::POLLIN) != 0)
}

fn cleanup_stale_socket(path: &str) {
    use std::os::unix::fs::FileTypeExt;
    match std::fs::symlink_metadata(path) {
        Ok(meta) if meta.file_type().is_socket() => {
            std::fs::remove_file(path).ok();
        }
        Ok(_) => log::warn!("{} exists but is not a socket, refusing to remove", path),
        Err(_) => {}
    }
}

fn handle_connection(
    stream: UnixStream,
    engine: &mut Engine,
    shutdown: &Arc<AtomicBool>,
) -> Result<()> {
    stream
        .set_read_timeout(Some(std::time::Duration::from_secs(1)))
        .ok();

    let mut reader = BufReader::new((&stream).take(MAX_CMD_LEN));
    let mut line = String::new();
    reader.read_line(&mut line)?;

    let line = line.trim();
    if line.is_empty() {
        return Ok(());
    }

    log::debug!("Received: {}", line);

    let cmd: Command = match serde_json::from_str(line) {
        Ok(c) => c,
        Err(e) => {
            let response = Response {
                ok: false,
                error: Some(format!("Invalid command: {}", e)),
                status: engine.status(),
            };
            return send_response(&stream, &response);
        }
    };

    let response = dispatch(cmd, engine, shutdown);
    send_response(&stream, &response)
}

fn dispatch(cmd: Command, engine: &mut Engine, shutdown: &Arc<AtomicBool>) -> Response {
    let error = match cmd {
        Command::Load { path } => engine.load(&path).err(),
        Command::Play => {
            engine.play();
            None
        }
        Command::Pause => {
            engine.pause();
            None
        }
        Command::Stop => {
            engine.stop();
            None
        }
        Command::Seek { position } => {
            engine.seek(position);
            None
        }
        Command::SetSpeed {
            speed,
            direction,
            ramp_ms,
        } => {
            engine.set_speed(speed, direction, ramp_ms);
            None
        }
        Command::SetVolume { volume } => {
            engine.set_volume(volume);
            None
        }
        Command::Status => None,
        Command::Quit => {
            log::info!("Quit command received");
            engine.stop();
            shutdown.store(true, Ordering::Relaxed);
            None
        }
    };

    Response {
        ok: error.is_none(),
        error: error.map(|e| format!("{:#}", e)),
        status: engine.status(),
    }
}

fn send_response(mut stream: &UnixStream, response: &Response) -> Result<()> {
    let mut json = serde_json::to_string(response)?;
    json.push('\n');
    log::debug!("Response: {}", json);
    stream.write_all(json.as_bytes())?;
    stream.flush()?;
    Ok(())
}

#[cfg(test)]
mod tests {
    use std::io::{BufRead, BufReader, Write};
    use std::os::unix::net::UnixStream;
    use std::sync::atomic::AtomicBool;
    use std::sync::Arc;

    use serde_json::Value;

    use super::handle_connection;
    use crate::engine::Engine;

    fn roundtrip(line: &str) -> Value {
        let (mut client, server) = UnixStream::pair().expect("pair");
        client.write_all(line.as_bytes()).expect("write request");
        client.flush().expect("flush request");

        let mut engine = Engine::new();
        let shutdown = Arc::new(AtomicBool::new(false));
        handle_connection(server, &mut engine, &shutdown).expect("handle connection");

        let mut reader = BufReader::new(client);
        let mut response_line = String::new();
        reader.read_line(&mut response_line).expect("read response");
        assert!(response_line.ends_with('\n'));

        serde_json::from_str(response_line.trim()).expect("parse response json")
    }

    #[test]
    fn invalid_json_returns_error_response() {
        let v = roundtrip("{not json}\n");
        assert_eq!(v["ok"], false);
        assert!(v["error"]
            .as_str()
            .unwrap_or("")
            .contains("Invalid command"));
    }

    #[test]
    fn quit_command_returns_ok_and_stopped() {
        let v = roundtrip("{\"cmd\":\"quit\"}\n");
        assert_eq!(v["ok"], true);
        assert_eq!(v["status"]["state"], "stopped");
    }

    #[test]
    fn oversized_command_is_rejected_cleanly() {
        let huge = format!("{}\n", "x".repeat(9000));
        let v = roundtrip(&huge);
        assert_eq!(v["ok"], false);
        assert!(v["error"]
            .as_str()
            .unwrap_or("")
            .contains("Invalid command"));
    }
}
