"""Command line entry point.

With no arguments this launches the GUI.  The flags exist so the same layout
logic can be scripted -- e.g. bind ``hyprlayout --apply-profile dock`` to a key.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Sequence

from . import __version__, hypr, luawriter
from .model import MonitorState
from .profiles import ProfileStore, state_to_json
from .snapping import validate


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hyprlayout",
        description="Drag-and-drop display arrangement for Hyprland. "
                    "Runs the GUI when given no options.",
    )
    parser.add_argument("--version", action="version", version=f"hyprlayout {__version__}")
    parser.add_argument("--status", action="store_true", help="print the current layout")
    parser.add_argument("--dump", action="store_true", help="print the current layout as JSON")
    parser.add_argument("--print-lua", action="store_true",
                        help="print the monitors.lua block for the current layout")
    parser.add_argument("--diff", action="store_true",
                        help="show what --save would change in monitors.lua")
    parser.add_argument("--save", action="store_true",
                        help="write the current layout to ~/.config/hypr/monitors.lua")
    parser.add_argument("--list-profiles", action="store_true", help="list saved profiles")
    parser.add_argument("--apply-profile", metavar="NAME",
                        help="apply a saved profile with hyprctl (no confirmation prompt)")
    parser.add_argument("--save-profile", metavar="NAME",
                        help="save the current layout as a profile")
    return parser


def _describe(states: Sequence[MonitorState]) -> str:
    lines = []
    for s in states:
        flag = " " if s.enabled else "×"
        w, h = s.logical_size
        lines.append(
            f"{flag} {s.name:<10} {s.pretty_name:<22} "
            f"{s.summary():<34} at {s.x},{s.y} ({round(w)}×{round(h)})"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    wants_cli = any(
        (args.status, args.dump, args.print_lua, args.diff, args.save,
         args.list_profiles, args.apply_profile, args.save_profile)
    )

    if not wants_cli:
        from .app import run  # imported lazily so CLI use needs no display

        return run([sys.argv[0]])

    if args.list_profiles:
        store = ProfileStore()
        names = store.names()
        if not names:
            print("no profiles saved")
        for name in names:
            profile = store.get(name)
            print(f"{name}\t{profile.fingerprint if profile else ''}")
        if not (args.status or args.dump or args.print_lua or args.diff
                or args.save or args.apply_profile or args.save_profile):
            return 0

    if not hypr.is_running():
        print("hyprlayout: HYPRLAND_INSTANCE_SIGNATURE is not set — "
              "is Hyprland running?", file=sys.stderr)
        return 2

    try:
        states = hypr.read_monitors()
    except hypr.HyprError as exc:
        print(f"hyprlayout: {exc}", file=sys.stderr)
        return 1

    if args.apply_profile:
        store = ProfileStore()
        profile = store.get(args.apply_profile)
        if profile is None:
            print(f"hyprlayout: no such profile: {args.apply_profile}", file=sys.stderr)
            return 1
        skipped = profile.apply_to(states)
        problems = validate(states)
        if any("disabled" in p for p in problems):
            print("hyprlayout: refusing to disable every display", file=sys.stderr)
            return 1
        for problem in problems:
            print(f"warning: {problem}", file=sys.stderr)
        try:
            hypr.apply_states(states)
        except hypr.HyprError as exc:
            print(f"hyprlayout: apply failed: {exc}", file=sys.stderr)
            return 1
        if skipped:
            print(f"applied {args.apply_profile} (not connected: {', '.join(skipped)})")
        else:
            print(f"applied {args.apply_profile}")

    if args.save_profile:
        ProfileStore().put(args.save_profile, states)
        print(f"saved profile {args.save_profile}")

    if args.status:
        print(_describe(states))

    if args.dump:
        print(json.dumps([state_to_json(s) for s in states], indent=2))

    if args.print_lua:
        print(luawriter.render_block(states), end="")

    if args.diff or args.save:
        path = luawriter.default_config_path()
        _, patch = luawriter.preview(path, states)
        if args.diff:
            print(patch, end="" if patch else "\n")
            if not patch:
                print(f"{path} already matches the current layout")
        if args.save:
            backup = luawriter.save(path, states)
            print(f"wrote {path}" + (f" (backup {backup.name})" if backup else ""))

    return 0
