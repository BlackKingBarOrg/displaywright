"""Talking to Hyprland: hyprctl for state and changes, socket2 for live events."""

from __future__ import annotations

import json
import os
import socket
import subprocess
import threading
from pathlib import Path
from typing import Callable, Iterable, Sequence

from .model import MonitorState


class HyprError(RuntimeError):
    pass


def instance_signature() -> str | None:
    return os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")


def is_running() -> bool:
    return instance_signature() is not None


def runtime_dir() -> Path | None:
    sig = instance_signature()
    if not sig:
        return None
    base = os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
    return Path(base) / "hypr" / sig


def _run(args: Sequence[str], timeout: float = 5.0) -> str:
    try:
        proc = subprocess.run(
            ["hyprctl", *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - depends on host
        raise HyprError("hyprctl not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:  # pragma: no cover
        raise HyprError(f"hyprctl {' '.join(args)} timed out") from exc
    if proc.returncode != 0:
        raise HyprError(proc.stderr.strip() or f"hyprctl {' '.join(args)} failed")
    return proc.stdout


def read_monitors() -> list[MonitorState]:
    """Current configuration of every known output, disabled ones included."""
    raw = _run(["-j", "monitors", "all"])
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise HyprError(f"could not parse hyprctl output: {exc}") from exc
    states = [MonitorState.from_hyprctl(entry) for entry in data]
    states.sort(key=lambda s: (not s.enabled, s.x, s.y, s.name))
    return states


#: Phrases hyprctl uses to refuse a request. It exits 0 regardless, so the reply
#: text is the only signal. "can't work with non-legacy parsers" is what a
#: Lua-configured Hyprland says about `keyword`.
_REJECTIONS = ("error", "can't work", "unknown request", "invalid dispatcher")


def _accepted(reply: str) -> bool:
    low = reply.lower()
    return not any(token in low for token in _REJECTIONS)


def apply_states(states: Iterable[MonitorState]) -> str:
    """Push monitor rules to the running compositor.

    Two dialects exist and neither is universal: Hyprland with a Lua config
    (0.56+) refuses ``keyword`` outright ("can't work with non-legacy parsers")
    and wants ``eval`` with Lua, while older hyprlang builds have no ``eval``.
    The modern form is tried first, the legacy one as a fallback.
    """
    states = list(states)
    if not states:
        return ""

    attempts = (
        ["eval", "; ".join(s.lua_call() for s in states)],
        ["--batch", " ; ".join(f"keyword monitor {s.rule_args()}" for s in states)],
    )
    problem = ""
    for args in attempts:
        reply = _run(args, timeout=20.0)
        if _accepted(reply):
            return reply
        problem = next((line for line in reply.splitlines() if line.strip()), "rejected")
    raise HyprError(f"Hyprland rejected the layout: {problem}")


def reload_config() -> str:
    return _run(["reload"], timeout=20.0)


def config_errors() -> str:
    out = _run(["configerrors"]).strip()
    return "" if out.lower().startswith("no errors") else out


def dispatch(*candidates: str) -> str:
    """Run the first dispatcher expression this Hyprland accepts.

    Hyprland 0.56 moved dispatchers into Lua (``hl.dsp.focus{monitor="DP-1"}``);
    older versions take the flat form (``focusmonitor DP-1``).  hyprctl exits 0
    for both a success and a rejected dispatcher, so success has to be read off
    the reply text.
    """
    problem = ""
    for expression in candidates:
        out = _run(["dispatch", expression])
        if _accepted(out):
            return out
        problem = next((line for line in out.splitlines() if line.strip()), "rejected")
    raise HyprError(problem or "no dispatcher form was accepted")


def focus_monitor(name: str) -> None:
    dispatch(f'hl.dsp.focus{{monitor="{name}"}}', f"focusmonitor {name}")


def move_cursor(x: int, y: int) -> None:
    dispatch(f"hl.dsp.cursor.move{{x={x}, y={y}}}", f"movecursor {x} {y}")


def notify(message: str, ms: int = 3000, icon: int = 1) -> None:
    """Best-effort on-screen notification through Hyprland itself."""
    try:
        _run(["notify", str(icon), str(ms), "rgb(8aadf4)", message])
    except HyprError:
        pass


class EventListener:
    """Watch Hyprland's socket2 for events that invalidate our view.

    ``on_event`` is called from a worker thread with the raw event name; GUI code
    is expected to marshal it onto the main loop.
    """

    WATCHED = (
        "monitoradded",
        "monitoraddedv2",
        "monitorremoved",
        "monitorremovedv2",
        "monitorlayoutchanged",
        "configreloaded",
    )

    def __init__(self, on_event: Callable[[str], None]) -> None:
        self._on_event = on_event
        self._thread: threading.Thread | None = None
        self._sock: socket.socket | None = None
        self._stop = threading.Event()

    def start(self) -> bool:
        rt = runtime_dir()
        if rt is None:
            return False
        path = rt / ".socket2.sock"
        if not path.exists():
            return False
        try:
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.connect(str(path))
        except OSError:
            return False
        self._sock = sock
        self._thread = threading.Thread(target=self._loop, name="hypr-events", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        sock, self._sock = self._sock, None
        if sock is not None:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()

    def _loop(self) -> None:
        sock = self._sock
        if sock is None:
            return
        buf = b""
        while not self._stop.is_set():
            try:
                chunk = sock.recv(4096)
            except OSError:
                break
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                name = line.decode("utf-8", "replace").split(">>", 1)[0].strip()
                if name in self.WATCHED:
                    self._on_event(name)
