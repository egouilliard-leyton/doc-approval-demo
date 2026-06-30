"""Offline tests for the Plannotator subprocess manager (Phase 3 Wave 1).

A ``FakePopen`` stands in for ``subprocess.Popen`` (injected via ``_popen=``) so no real
process is spawned. ``communicate()`` blocks on a ``threading.Event`` to model a session
the user hasn't finished, then returns canned stdout once released — letting us observe
the pending -> done transition the reader thread drives.
"""

import threading
import time

import pytest

from app import annotate_proc as ap


class FakePopen:
    """A subprocess.Popen stand-in whose communicate() blocks until released."""

    def __init__(self, stdout_bytes: bytes = b"", *, fail_communicate: bool = False):
        self.pid = 4242
        self._stdout = stdout_bytes
        self._release = threading.Event()
        self.terminated = False

    def communicate(self, timeout=None):
        self._release.wait()
        return self._stdout, b""

    def release(self):
        self._release.set()

    def terminate(self):
        self.terminated = True
        self._release.set()  # unblock the reader so the thread can exit


def _wait_until(predicate, timeout=2.0):
    """Poll a predicate without a fixed sleep; returns its (truthy) result or fails."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("condition not met within timeout")


# --- launch -------------------------------------------------------------------


def test_launch_raises_when_server_never_ready():
    """If the port never starts listening, launch fails cleanly (no leaked session)."""
    fake = FakePopen(b'{"decision": "approve"}')
    with pytest.raises(ValueError, match="did not start listening"):
        ap.launch_session(
            "# Spec\n", _popen=lambda *a, **k: fake, _ready=lambda *a, **k: False
        )
    assert fake.terminated


def test_launch_returns_session_and_url():
    fake = FakePopen(b'{"decision": "approve", "feedback": "looks good"}')
    session_id, url = ap.launch_session("# Spec\n", _popen=lambda *a, **k: fake, _ready=lambda *a, **k: True)
    try:
        assert session_id
        assert url.startswith("http://127.0.0.1:")
        assert url.endswith("/")
    finally:
        fake.release()
        ap.cancel_session(session_id)


# --- poll pending then done ---------------------------------------------------


def test_poll_pending_then_done():
    fake = FakePopen(b'{"decision": "request_changes", "feedback": "add a field"}')
    session_id, _ = ap.launch_session("# Spec\n", _popen=lambda *a, **k: fake, _ready=lambda *a, **k: True)

    assert ap.poll_session(session_id) == {"status": "pending"}

    fake.release()
    done = _wait_until(
        lambda: (p := ap.poll_session(session_id))["status"] == "done" and p
    )
    assert done["decision"] == "request_changes"
    assert done["feedback"] == "add a field"
    assert done["raw"]["decision"] == "request_changes"
    ap.cancel_session(session_id)


# --- poll unknown -------------------------------------------------------------


def test_poll_unknown_returns_none():
    assert ap.poll_session("does-not-exist") is None


# --- plannotator missing -> ValueError ----------------------------------------


def test_missing_binary_raises_value_error():
    def boom(*a, **k):
        raise FileNotFoundError("plannotator")

    with pytest.raises(ValueError, match="plannotator not found"):
        ap.launch_session("# Spec\n", _popen=boom)


# --- cancel terminates + removes ----------------------------------------------


def test_cancel_terminates_and_removes():
    fake = FakePopen(b'{"decision": "approve"}')
    session_id, _ = ap.launch_session("# Spec\n", _popen=lambda *a, **k: fake, _ready=lambda *a, **k: True)
    assert ap.cancel_session(session_id) is True
    assert fake.terminated is True
    assert ap.poll_session(session_id) is None
    # Cancelling an unknown / already-removed session is False.
    assert ap.cancel_session(session_id) is False


# --- stdout not JSON -> synthetic error decision ------------------------------


def test_non_json_stdout_yields_error_decision():
    fake = FakePopen(b"not json at all")
    session_id, _ = ap.launch_session("# Spec\n", _popen=lambda *a, **k: fake, _ready=lambda *a, **k: True)
    fake.release()
    done = _wait_until(
        lambda: (p := ap.poll_session(session_id))["status"] == "done" and p
    )
    assert done["decision"] == "error"
    assert "not valid JSON" in done["feedback"]
    ap.cancel_session(session_id)


def test_temp_file_unlinked_after_done():
    from pathlib import Path

    fake = FakePopen(b'{"decision": "approve"}')
    session_id, _ = ap.launch_session("# Spec\n", _popen=lambda *a, **k: fake, _ready=lambda *a, **k: True)
    with ap._LOCK:
        tmp_path = ap._SESSIONS[session_id].tmp_path
    assert Path(tmp_path).exists()
    fake.release()
    _wait_until(lambda: not Path(tmp_path).exists())
    ap.cancel_session(session_id)
