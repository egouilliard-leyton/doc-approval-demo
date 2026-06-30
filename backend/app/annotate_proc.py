"""Plannotator annotation subprocess manager.

The wizard renders a spec to markdown and asks the user to annotate it in Plannotator's
browser UI. Each session spawns ``plannotator annotate <file> --json`` as a child
process listening on a free local port; a daemon reader thread drains its stdout (the
final ``--json`` decision/feedback) when the user finishes. Sessions are tracked in a
module-level registry guarded by a lock, and a background reaper unlinks stale ones.

This module has NO FastAPI imports — it is importable and unit-testable standalone. The
subprocess launcher is injectable (``_popen=``) so tests never start a real process.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from app.config import settings


@dataclass
class _AnnotateSession:
    """One live (or finished) Plannotator annotation session."""

    session_id: str
    pid: int
    port: int
    url: str
    tmp_path: str
    proc: object  # subprocess.Popen (or a test double exposing communicate/terminate)
    result: dict | None = None
    exited: bool = False
    created_at: float = 0.0


_SESSIONS: dict[str, _AnnotateSession] = {}
_LOCK = threading.Lock()


def _free_port() -> int:
    """Pick an available localhost TCP port by binding to port 0 and reading it back."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# Plannotator (Bun) takes ~1-2s to actually start listening after the fork. We must not
# hand the URL to the browser before then, or the iframe gets "connection refused" and
# does not retry. Poll the port until the server accepts a connection (or the process
# dies / we time out).
_READY_TIMEOUT_S = 20.0
_READY_POLL_S = 0.1


def _wait_until_ready(port: int, proc, timeout: float = _READY_TIMEOUT_S) -> bool:
    """Block until ``port`` accepts a TCP connection, returning ``False`` on timeout.

    Returns ``False`` immediately if the subprocess exits before binding (it crashed).
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if proc.poll() is not None:  # process exited before it ever listened
            return False
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(_READY_POLL_S)
    return False


def _reader_thread(session: _AnnotateSession) -> None:
    """Drain the subprocess stdout, parse the JSON decision, and mark the session done.

    Falls back to the last valid JSON line, then to a synthetic ``error`` decision when
    the output is not JSON at all. Always unlinks the temp file when finished.
    """
    out, _ = session.proc.communicate()
    text = out.decode("utf-8", errors="replace") if isinstance(out, (bytes, bytearray)) else str(out)
    result = _parse_annotator_output(text)
    with _LOCK:
        session.result = result
        session.exited = True
    Path(session.tmp_path).unlink(missing_ok=True)


def _parse_annotator_output(text: str) -> dict:
    """Parse Plannotator's stdout into a decision dict, tolerating noise before the JSON."""
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001 — try the last valid JSON line, else synthesize
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                return json.loads(line)
            except Exception:  # noqa: BLE001
                continue
    return {
        "decision": "error",
        "feedback": f"plannotator output not valid JSON: {text[:200]}",
    }


def launch_session(
    spec_markdown: str, *, _popen=subprocess.Popen, _ready=_wait_until_ready
) -> tuple[str, str]:
    """Write ``spec_markdown`` to a temp file and launch a Plannotator session over it.

    Returns ``(session_id, url)`` only once the server is actually accepting connections,
    so the browser iframe never hits a "connection refused". Raises :class:`ValueError`
    if the ``plannotator`` binary is not on PATH or fails to start listening in time
    (after cleaning up the temp file + child). ``_ready`` is injectable for tests.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".md", delete=False, mode="w", encoding="utf-8")
    try:
        tmp.write(spec_markdown)
        tmp.flush()
    finally:
        tmp.close()
    tmp_path = tmp.name

    port = _free_port()
    url = f"http://127.0.0.1:{port}/"
    env = {
        **os.environ,
        "PLANNOTATOR_SKIP_BROWSER_OPEN": "1",
        "PLANNOTATOR_PORT": str(port),
    }
    try:
        proc = _popen(
            ["plannotator", "annotate", tmp_path, "--json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )
    except (FileNotFoundError, OSError) as exc:
        Path(tmp_path).unlink(missing_ok=True)
        raise ValueError(
            "plannotator not found on PATH; cannot start annotation session"
        ) from exc

    if not _ready(port, proc):
        # Server never came up (crash or too slow): kill + reap the child, clean up, fail.
        try:
            proc.terminate()
            proc.communicate(timeout=2)
        except Exception:  # noqa: BLE001 — best-effort teardown
            pass
        Path(tmp_path).unlink(missing_ok=True)
        raise ValueError(
            f"plannotator did not start listening on port {port} in time"
        )

    session_id = uuid4().hex
    session = _AnnotateSession(
        session_id=session_id,
        pid=getattr(proc, "pid", -1),
        port=port,
        url=url,
        tmp_path=tmp_path,
        proc=proc,
        created_at=time.time(),
    )
    with _LOCK:
        _SESSIONS[session_id] = session

    thread = threading.Thread(target=_reader_thread, args=(session,), daemon=True)
    thread.start()
    return session_id, url


def poll_session(session_id: str) -> dict | None:
    """Return the session status, or ``None`` if the id is unknown.

    ``{"status": "pending"}`` while running; once finished, ``{"status": "done",
    "decision", "feedback", "raw"}`` from the parsed result.
    """
    with _LOCK:
        session = _SESSIONS.get(session_id)
        if session is None:
            return None
        if not session.exited:
            return {"status": "pending"}
        result = session.result or {}
        return {
            "status": "done",
            "decision": result.get("decision"),
            "feedback": result.get("feedback"),
            "raw": result,
        }


def cancel_session(session_id: str) -> bool:
    """Terminate a running session (if any) and drop it from the registry.

    Returns ``True`` if the session existed, ``False`` otherwise. Always unlinks the temp.
    """
    with _LOCK:
        session = _SESSIONS.pop(session_id, None)
    if session is None:
        return False
    if not session.exited:
        try:
            session.proc.terminate()
        except Exception:  # noqa: BLE001 — best-effort kill, already-dead is fine
            pass
    Path(session.tmp_path).unlink(missing_ok=True)
    return True


def _reaper_loop() -> None:
    """Daemon loop: every 60s, cancel sessions idle longer than ``annotate_ttl_s``."""
    while True:
        time.sleep(60)
        now = time.time()
        with _LOCK:
            stale = [
                sid
                for sid, s in _SESSIONS.items()
                if now - s.created_at > settings.annotate_ttl_s
            ]
        for sid in stale:
            cancel_session(sid)


_reaper_thread = threading.Thread(target=_reaper_loop, daemon=True)
_reaper_thread.start()


__all__ = ["launch_session", "poll_session", "cancel_session"]
