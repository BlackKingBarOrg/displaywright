"""Named layout profiles, stored as JSON under ``~/.config/hyprlayout``.

A profile records the desired configuration of a set of outputs plus a
*fingerprint* of the outputs it was saved with, so "dock" and "laptop only" can
be recognised automatically when displays come and go.
"""

from __future__ import annotations

import json
import os
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from .model import Mode, MonitorState

SCHEMA = 1


def default_store_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "hyprlayout" / "profiles.json"


def output_key(state: MonitorState) -> str:
    """Stable identity for one output: name plus EDID description."""
    return f"{state.name}|{state.description}".strip("|")


def fingerprint(states: Sequence[MonitorState]) -> str:
    return " + ".join(sorted(output_key(s) for s in states))


def _mode_to_json(mode: Mode | None) -> dict | None:
    if mode is None:
        return None
    return {"width": mode.width, "height": mode.height, "refresh": mode.refresh}


def _mode_from_json(data: dict | None) -> Mode | None:
    if not data:
        return None
    return Mode(int(data["width"]), int(data["height"]), float(data.get("refresh") or 0.0))


def state_to_json(state: MonitorState) -> dict:
    return {
        "name": state.name,
        "description": state.description,
        "enabled": state.enabled,
        "mode": _mode_to_json(state.mode),
        "scale": state.scale,
        "transform": state.transform,
        "x": state.x,
        "y": state.y,
        "vrr": state.vrr,
        "mirror_of": state.mirror_of,
    }


@dataclass
class Profile:
    name: str
    fingerprint: str
    monitors: list[dict]

    def to_json(self) -> dict:
        return {"fingerprint": self.fingerprint, "monitors": self.monitors}

    @classmethod
    def from_states(cls, name: str, states: Sequence[MonitorState]) -> Profile:
        return cls(name, fingerprint(states), [state_to_json(s) for s in states])

    def apply_to(self, live: Sequence[MonitorState]) -> list[str]:
        """Copy saved settings onto live states in place; returns skipped names."""
        by_name = {s.name: s for s in live}
        by_desc = {s.description: s for s in live if s.description}
        skipped: list[str] = []
        for entry in self.monitors:
            target = by_name.get(entry["name"]) or by_desc.get(entry.get("description", ""))
            if target is None:
                skipped.append(entry["name"])
                continue
            target.enabled = bool(entry.get("enabled", True))
            mode = _mode_from_json(entry.get("mode"))
            if mode is not None and target.available_modes and mode not in target.available_modes:
                # Saved mode is gone (different cable/link) -- fall back to preferred.
                mode = None
            target.mode = mode
            target.scale = float(entry.get("scale") or 1.0)
            target.transform = int(entry.get("transform") or 0)
            target.x = int(entry.get("x") or 0)
            target.y = int(entry.get("y") or 0)
            vrr = entry.get("vrr")
            target.vrr = None if vrr is None else int(vrr)
            target.mirror_of = entry.get("mirror_of") or None
        return skipped


class ProfileStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_store_path()
        self._profiles: dict[str, Profile] = {}
        self.load()

    def load(self) -> None:
        self._profiles = {}
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            return
        for name, entry in (data.get("profiles") or {}).items():
            self._profiles[name] = Profile(
                name=name,
                fingerprint=entry.get("fingerprint", ""),
                monitors=entry.get("monitors", []),
            )

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema": SCHEMA,
            "profiles": {name: p.to_json() for name, p in self._profiles.items()},
        }
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
        tmp.replace(self.path)

    # ------------------------------------------------------------------ access

    def names(self) -> list[str]:
        return sorted(self._profiles)

    def get(self, name: str) -> Profile | None:
        return self._profiles.get(name)

    def put(self, name: str, states: Sequence[MonitorState]) -> Profile:
        profile = Profile.from_states(name, states)
        self._profiles[name] = profile
        self.save()
        return profile

    def delete(self, name: str) -> bool:
        if name in self._profiles:
            del self._profiles[name]
            self.save()
            return True
        return False

    def match(self, states: Sequence[MonitorState]) -> Profile | None:
        """The profile saved for exactly this set of outputs, if any."""
        fp = fingerprint(states)
        for profile in self._profiles.values():
            if profile.fingerprint == fp:
                return profile
        return None
