"""Cross-platform pseudo-terminal I/O (effect edge, N8).

A pane's command runs inside a real PTY so it behaves exactly as it would in a
terminal — colours, cursor moves, `clear`, progress bars all work — and the
recorder reads the bytes it prints. Two backends implement one interface:

* POSIX (Linux, macOS): the stdlib `pty` module + a fixed window size.
* Windows: `pywinpty` (ConPTY), an optional dependency pulled in by the
  `pocyeah[record]` extra's platform marker.

Both drain through a background reader thread into a buffer, so the recorder's
frame loop only ever does a non-blocking `read_output()` and never stalls
waiting on a quiet pane. `open_pane()` picks the backend for the current OS.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from typing import Protocol


class PtyPane(Protocol):
    """A launched command attached to a PTY, read without blocking."""

    def read_output(self) -> bytes:
        """Return and clear everything read since the last call (maybe b'')."""

    def is_alive(self) -> bool:
        """True while the child process is still running."""

    def terminate(self) -> None:
        """Ask the child (and its group) to stop; escalate to a hard kill."""

    def close(self) -> None:
        """Release the PTY resources. Safe to call more than once."""


class _BufferedReader:
    """Shared drain buffer + background reader thread for both backends."""

    def __init__(self) -> None:
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._eof = threading.Event()

    def _pump(self, read_chunk) -> None:
        while True:
            try:
                data = read_chunk()
            except (OSError, EOFError):
                break
            if not data:
                break
            with self._lock:
                self._buf.extend(data)
        self._eof.set()

    def start(self, read_chunk) -> None:
        self._thread = threading.Thread(target=self._pump, args=(read_chunk,), daemon=True)
        self._thread.start()

    def read_output(self) -> bytes:
        with self._lock:
            if not self._buf:
                return b""
            data = bytes(self._buf)
            self._buf.clear()
            return data


class PosixPtyPane:
    """POSIX PTY pane: a child in its own session, driven through a master fd."""

    def __init__(
        self, cmd: str, env: dict[str, str], cwd: str | None, cols: int, rows: int
    ) -> None:
        import fcntl
        import pty
        import struct
        import termios

        master, slave = pty.openpty()
        # Tell the child its window size so full-screen TUIs and line wrapping match
        # the pane we render into.
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(slave, termios.TIOCSWINSZ, winsize)

        full_env = dict(env)
        full_env.setdefault("TERM", "xterm-256color")
        full_env.setdefault("COLUMNS", str(cols))
        full_env.setdefault("LINES", str(rows))

        self._proc = subprocess.Popen(
            ["/bin/sh", "-c", cmd],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=cwd,
            env=full_env,
            close_fds=True,
            start_new_session=True,  # own process group, so terminate() kills children
        )
        os.close(slave)
        self._master = master
        self._reader = _BufferedReader()
        self._reader.start(lambda: os.read(master, 65536))

    def read_output(self) -> bytes:
        return self._reader.read_output()

    def is_alive(self) -> bool:
        return self._proc.poll() is None

    def terminate(self) -> None:
        import signal

        if self._proc.poll() is not None:
            return
        try:
            os.killpg(os.getpgid(self._proc.pid), signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            self._proc.terminate()
        try:
            self._proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(os.getpgid(self._proc.pid), signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                self._proc.kill()

    def close(self) -> None:
        try:
            os.close(self._master)
        except OSError:
            pass


class WindowsPtyPane:
    """Windows PTY pane backed by pywinpty (ConPTY)."""

    def __init__(
        self, cmd: str, env: dict[str, str], cwd: str | None, cols: int, rows: int
    ) -> None:
        try:
            from winpty import PtyProcess
        except ImportError as e:  # pragma: no cover - exercised only on Windows
            raise RuntimeError(
                "recording on Windows needs pywinpty. Install the recorder extra: "
                "pip install 'pocyeah[record]'"
            ) from e

        full_env = dict(env)
        full_env.setdefault("TERM", "xterm-256color")
        # ConPTY runs a command line; go through cmd.exe so shell syntax in a
        # pane's `cmd` (pipes, &&, quoting) works the same as /bin/sh -c on POSIX.
        spawn = f'cmd.exe /c "{cmd}"'
        self._proc = PtyProcess.spawn(
            spawn, dimensions=(rows, cols), cwd=cwd, env=full_env
        )
        self._reader = _BufferedReader()
        # pywinpty's read returns str; re-encode to bytes for the shared pipeline.
        self._reader.start(self._read_chunk)

    def _read_chunk(self) -> bytes:  # pragma: no cover - Windows-only
        data = self._proc.read(65536)
        if data == "":
            raise EOFError
        return data.encode("utf-8", "replace")

    def read_output(self) -> bytes:  # pragma: no cover - Windows-only
        return self._reader.read_output()

    def is_alive(self) -> bool:  # pragma: no cover - Windows-only
        return self._proc.isalive()

    def terminate(self) -> None:  # pragma: no cover - Windows-only
        try:
            self._proc.terminate(force=True)
        except Exception:  # noqa: BLE001 - best-effort teardown
            pass

    def close(self) -> None:  # pragma: no cover - Windows-only
        try:
            self._proc.close()
        except Exception:  # noqa: BLE001
            pass


def open_pane(
    cmd: str, env: dict[str, str], cwd: str | None, cols: int, rows: int
) -> PtyPane:
    """Launch `cmd` in a PTY sized `cols x rows`, picking the OS backend."""
    if sys.platform == "win32":  # pragma: no cover - selected only on Windows
        return WindowsPtyPane(cmd, env, cwd, cols, rows)
    return PosixPtyPane(cmd, env, cwd, cols, rows)
