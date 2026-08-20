"""Command line entry point. With no arguments this opens the GUI.

The two halves keep their own noun -- ``layout`` for where the displays are,
``wallpaper`` for what they draw -- because they are genuinely different jobs
with different risks. Everything a subcommand does is what clicking through the
window would have done, so ``displaywright wallpaper set DP-1 ~/a.jpg`` or
``displaywright layout profile-apply dock`` can be bound to a key.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from . import __version__, hypr, migrate
from .displays import luawriter, omarchy
from .displays.profiles import ProfileStore, state_to_json
from .displays.snapping import validate
from .model import MonitorState
from .paths import display_path
from .wallpapers import library, plugin, shell, span, store
from .wallpapers.model import Config, Fit, Kind, Source, is_color, kind_for_path

PROG = "displaywright"
SPAN = "span"


# ------------------------------------------------------------------- plumbing


def _fail(message: str) -> int:
    print(f"{PROG}: {message}", file=sys.stderr)
    return 1


def _read_layout() -> list[MonitorState]:
    if not hypr.is_running():
        raise hypr.HyprError("HYPRLAND_INSTANCE_SIGNATURE is not set — is Hyprland running?")
    return hypr.read_monitors()


def _lit(states: Sequence[MonitorState]) -> list[MonitorState]:
    return [s for s in states if s.enabled]


# --------------------------------------------------------------------- parser


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Display arrangement and per-display wallpapers for Hyprland "
                    "and Omarchy. Opens the GUI when given no command.",
    )
    parser.add_argument("--version", action="version", version=f"{PROG} {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("outputs", help="list the displays Hyprland reports")

    layout = sub.add_parser(
        "layout", help="where the displays are"
    ).add_subparsers(dest="action", required=True)
    layout.add_parser("status", help="print the current arrangement")
    layout.add_parser("dump", help="print the current arrangement as JSON")
    layout.add_parser("lua", help="print the monitors.lua block for the current arrangement")
    layout.add_parser("diff", help="show what `layout save` would change in monitors.lua")
    layout.add_parser("save", help="write the current arrangement to ~/.config/hypr/monitors.lua")
    p_builtin = layout.add_parser(
        "builtin",
        help="switch the built-in laptop panel on or off",
        description="Off is kept only while an external display is connected: Omarchy "
                    "switches the panel back on when none is left, whether or not this "
                    "tool is running.",
    )
    p_builtin.add_argument("state", choices=("on", "off", "toggle"))
    layout.add_parser("profiles", help="list saved arrangement profiles")
    for name, help_text in (
        ("profile-apply", "apply a saved profile with hyprctl (no confirmation prompt)"),
        ("profile-save", "save the current arrangement as a profile"),
        ("profile-delete", "forget a saved profile"),
    ):
        layout.add_parser(name, help=help_text).add_argument("name", metavar="NAME")

    wallpaper = sub.add_parser(
        "wallpaper", help="what the displays draw"
    ).add_subparsers(dest="action", required=True)
    wallpaper.add_parser("status", help="show what each display is drawing")

    fits = [str(f) for f in Fit]
    p_set = wallpaper.add_parser("set", help="put a picture on one display")
    p_set.add_argument("output", help="output name, or 'span' to stretch across every display")
    p_set.add_argument("path", help="image or video file")
    p_set.add_argument("--fit", choices=fits, default=None,
                       help=f"how it fills the display ({', '.join(fits)}); default keeps the "
                            "current one, or fill")
    p_set.add_argument("--backdrop", metavar="HEX", default=None,
                       help="colour behind a fit or centre, e.g. #101010")
    p_set.add_argument("--no-copy", action="store_true",
                       help="point at the file where it is instead of copying it into "
                            f"{library.wallpaper_dir()}")

    p_color = wallpaper.add_parser("color", help="put a flat colour on one display")
    p_color.add_argument("output")
    p_color.add_argument("color", metavar="HEX")

    p_clear = wallpaper.add_parser("clear", help="hand a display back to the theme background")
    p_clear.add_argument("output", nargs="*", help="defaults to every display")

    renderer = sub.add_parser(
        "renderer", help="the omarchy-shell plugin that draws the wallpapers"
    ).add_subparsers(dest="action", required=True)
    renderer.add_parser("status", help="say whether the renderer is installed and active")
    renderer.add_parser("install", help="install the renderer into omarchy-shell").add_argument(
        "--copy", action="store_true", help="copy the plugin instead of linking this checkout"
    )
    renderer.add_parser("uninstall", help="give the background layer back to Omarchy")

    p_migrate = sub.add_parser(
        "migrate",
        help="move a wallwright / hyprlayout installation over to displaywright",
    )
    p_migrate.add_argument("--dry-run", action="store_true",
                           help="say whether anything is left to migrate, and change nothing")
    p_migrate.add_argument("--copy", action="store_true",
                           help="copy the renderer plugin instead of linking this checkout")

    return parser


# --------------------------------------------------------------------- shared


def _cmd_outputs() -> int:
    try:
        states = _read_layout()
    except hypr.HyprError as exc:
        return _fail(str(exc))
    for s in states:
        flag = " " if s.enabled else "×"
        print(f"{flag} {s.name:<10} {s.pretty_name:<28} {s.panel_summary():<34} at {s.x},{s.y}")
    return 0


# --------------------------------------------------------------------- layout


def _describe_layout(states: Sequence[MonitorState]) -> str:
    lines = []
    if omarchy.is_disabled():
        lines.append("  built-in panel held off by Omarchy's internal-monitor-disable toggle")
    for s in states:
        flag = " " if s.enabled else "×"
        w, h = s.logical_size
        lines.append(
            f"{flag} {s.name:<10} {s.pretty_name:<22} "
            f"{s.summary():<34} at {s.x},{s.y} ({round(w)}×{round(h)})"
        )
    return "\n".join(lines)


def _switch_builtin(action: str, states: list[MonitorState]) -> int:
    """Turn the laptop panel off (or back on) the way Omarchy can recover from."""
    panel = omarchy.builtin(states)
    if panel is None:
        return _fail("no built-in display found")

    turn_off = action == "off" or (action == "toggle" and not omarchy.is_disabled())

    if turn_off:
        if not [s for s in states if not s.is_builtin and s.enabled]:
            return _fail(
                "refusing to switch off the only display — connect an external display first"
            )
        panel.enabled = False
        try:
            hypr.apply_states(states)
        except hypr.HyprError as exc:
            return _fail(str(exc))
        if omarchy.available():
            omarchy.disable_builtin(panel.name)
            print(f"{panel.name} off. It comes back automatically when no external "
                  "display is left.")
        else:
            print(f"{panel.name} off for this session only (no Omarchy toggle here).")
        return 0

    cleared = omarchy.enable_builtin() if omarchy.available() else False
    try:
        # A reload re-applies monitors.lua, which restores the panel's geometry.
        hypr.reload_config()
    except hypr.HyprError as exc:
        return _fail(str(exc))
    print(f"{panel.name} on{' (toggle cleared)' if cleared else ''}.")
    return 0


def _cmd_layout(args: argparse.Namespace) -> int:
    action = args.action
    store_ = ProfileStore()

    if action == "profiles":
        names = store_.names()
        if not names:
            print("no profiles saved")
        for name in names:
            profile = store_.get(name)
            print(f"{name}\t{profile.fingerprint if profile else ''}")
        return 0

    if action == "profile-delete":
        if not store_.delete(args.name):
            return _fail(f"no such profile: {args.name}")
        print(f"deleted profile {args.name}")
        return 0

    try:
        states = _read_layout()
    except hypr.HyprError as exc:
        return _fail(str(exc))

    if action == "builtin":
        return _switch_builtin(args.state, states)

    if action == "profile-save":
        store_.put(args.name, states)
        print(f"saved profile {args.name}")
        return 0

    if action == "profile-apply":
        profile = store_.get(args.name)
        if profile is None:
            return _fail(f"no such profile: {args.name}")
        skipped = profile.apply_to(states)
        problems = validate(states)
        if any("disabled" in p for p in problems):
            return _fail("refusing to disable every display")
        for problem in problems:
            print(f"warning: {problem}", file=sys.stderr)
        try:
            hypr.apply_states(states)
        except hypr.HyprError as exc:
            return _fail(f"apply failed: {exc}")
        if skipped:
            print(f"applied {args.name} (not connected: {', '.join(skipped)})")
        else:
            print(f"applied {args.name}")
        return 0

    if action == "status":
        print(_describe_layout(states))
        return 0

    if action == "dump":
        print(json.dumps([state_to_json(s) for s in states], indent=2))
        return 0

    if action == "lua":
        print(luawriter.render_block(states), end="")
        return 0

    path = luawriter.default_config_path()
    if action == "diff":
        _, patch = luawriter.preview(path, states)
        if patch:
            print(patch, end="")
        else:
            print(f"{display_path(path)} already matches the current layout")
        return 0

    if action == "save":
        backup = luawriter.save(path, states, toggle_builtin=omarchy.available())
        print(f"wrote {display_path(path)}" + (f" (backup {backup.name})" if backup else ""))
        return 0

    return _fail(f"unknown layout action: {action}")


# ------------------------------------------------------------------ wallpaper


def _apply_wallpapers(cfg: Config) -> None:
    path = store.save(cfg)
    delivered = shell.reload()
    print(f"wrote {display_path(path)}" + ("" if delivered else " (omarchy-shell not reachable; "
                                                                "it will pick the change up on "
                                                                "its own)"))


def _resolve_output(name: str, states: Sequence[MonitorState]) -> str | None:
    return next((s.name for s in states if s.name == name), None)


def _cmd_wallpaper_status(cfg: Config) -> int:
    print(f"renderer: {plugin.status().describe()}")
    try:
        states = _lit(_read_layout())
    except hypr.HyprError as exc:
        return _fail(str(exc))

    if cfg.span is not None:
        covered = span.coverage(states)
        box = span.span_box(states)
        print(f"span:     {cfg.span.describe()}")
        if box is not None:
            print(f"          {round(box.w)}×{round(box.h)} across {len(states)} displays, "
                  f"{covered * 100:.0f}% of it on glass")
    for state in states:
        source = cfg.source_for(state.name)
        if source is None:
            what = "follows the theme background"
        elif cfg.span is not None:
            offset = span.offsets(states).get(state.name, (0, 0))
            what = f"span at +{offset[0]},+{offset[1]}"
        else:
            what = source.describe() + ("  (file is missing)" if source.missing() else "")
        print(f"{state.name:<10} {state.panel_summary():<34} {what}")
    return 0


def _cmd_wallpaper_set(args: argparse.Namespace, cfg: Config) -> int:
    path = Path(args.path).expanduser()
    if not path.is_file():
        return _fail(f"no such file: {path}")
    kind = kind_for_path(path)
    if kind is None:
        return _fail(f"not a picture or video displaywright can draw: {path.name}")

    if not args.no_copy:
        # Keeps the wallpaper working after the original is moved or deleted.
        try:
            adoption = library.adopt(path)
        except OSError as exc:
            print(f"{PROG}: keeping the original, could not copy it in: {exc}", file=sys.stderr)
        else:
            note = adoption.describe()
            if note:
                print(note)
            path = adoption.path

    target = args.output
    if target != SPAN:
        try:
            states = _lit(_read_layout())
        except hypr.HyprError as exc:
            return _fail(str(exc))
        resolved = _resolve_output(target, states)
        if resolved is None:
            names = ", ".join(s.name for s in states) or "none"
            return _fail(f"no such display: {target} (have: {names}, or 'span')")
        target = resolved

    previous = cfg.span if target == SPAN else cfg.monitors.get(target)
    fit = Fit(args.fit) if args.fit else (previous.fit if previous else Fit.FILL)
    backdrop = args.backdrop or (previous.backdrop if previous else None)
    if backdrop is not None and not is_color(backdrop):
        return _fail(f"not a hex colour: {backdrop}")

    source = Source(kind=kind, path=str(path.resolve()), fit=fit)
    if backdrop:
        source.backdrop = backdrop

    if target == SPAN:
        if args.fit:
            print(f"{PROG}: --fit is ignored for a span; it always covers the bounding box "
                  "of every display", file=sys.stderr)
        cfg.span = source
    else:
        cfg.pin(target, source)
    _apply_wallpapers(cfg)
    return 0


def _cmd_wallpaper_color(args: argparse.Namespace, cfg: Config) -> int:
    if not is_color(args.color):
        return _fail(f"not a hex colour: {args.color}")
    target = args.output
    source = Source(kind=Kind.COLOR, color=args.color)
    if target == SPAN:
        cfg.span = source
    else:
        try:
            states = _lit(_read_layout())
        except hypr.HyprError as exc:
            return _fail(str(exc))
        resolved = _resolve_output(target, states)
        if resolved is None:
            return _fail(f"no such display: {target}")
        cfg.pin(resolved, source)
    _apply_wallpapers(cfg)
    return 0


def _cmd_wallpaper_clear(args: argparse.Namespace, cfg: Config) -> int:
    if not args.output:
        cfg.monitors.clear()
        cfg.span = None
        _apply_wallpapers(cfg)
        return 0
    for name in args.output:
        if name == SPAN:
            cfg.span = None
        elif not cfg.unpin(name):
            print(f"{PROG}: {name} was already following the theme", file=sys.stderr)
    _apply_wallpapers(cfg)
    return 0


def _cmd_wallpaper(args: argparse.Namespace) -> int:
    cfg = store.load()
    if args.action == "status":
        return _cmd_wallpaper_status(cfg)
    if args.action == "set":
        return _cmd_wallpaper_set(args, cfg)
    if args.action == "color":
        return _cmd_wallpaper_color(args, cfg)
    if args.action == "clear":
        return _cmd_wallpaper_clear(args, cfg)
    return _fail(f"unknown wallpaper action: {args.action}")


# ------------------------------------------------------------------- renderer


def _nudge_shell() -> None:
    if shell.is_running():
        shell.call("shell", "reloadConfig")
        shell.rescan_plugins()
        print("omarchy-shell reloaded")
    else:
        print("omarchy-shell is not running; the renderer starts with your next session")


def _cmd_renderer(args: argparse.Namespace) -> int:
    if args.action == "status":
        print(plugin.status().describe())
        return 0
    if args.action == "install":
        if not plugin.is_omarchy():
            return _fail(f"this does not look like an Omarchy system ({plugin.omarchy_path()})")
        try:
            changed = plugin.install(link=not args.copy)
        except (OSError, FileNotFoundError) as exc:
            return _fail(str(exc))
        for line in changed:
            print(line)
        if not changed:
            print("already installed")
        _nudge_shell()
        return 0
    if args.action == "uninstall":
        changed = plugin.uninstall()
        for line in changed:
            print(line)
        if not changed:
            print("was not installed")
        _nudge_shell()
        return 0
    return _fail(f"unknown renderer action: {args.action}")


# -------------------------------------------------------------------- migrate


def _cmd_migrate(args: argparse.Namespace) -> int:
    if args.dry_run:
        if migrate.pending():
            print("there is a wallwright / hyprlayout installation left to migrate")
            return 0
        print("nothing left to migrate")
        return 0
    changed = migrate.run(link=not args.copy)
    for line in changed:
        print(line)
    if not changed:
        print("nothing to migrate")
        return 0
    _nudge_shell()
    return 0


# ----------------------------------------------------------------------- main


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)

    if args.command is None:
        from .app import run  # imported lazily so CLI use needs no display

        return run([sys.argv[0]])

    if args.command == "outputs":
        return _cmd_outputs()
    if args.command == "layout":
        return _cmd_layout(args)
    if args.command == "wallpaper":
        return _cmd_wallpaper(args)
    if args.command == "renderer":
        return _cmd_renderer(args)
    if args.command == "migrate":
        return _cmd_migrate(args)

    return _fail(f"unknown command: {args.command}")
