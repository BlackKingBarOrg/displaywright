# hyprlayout

Arrange your Hyprland displays by dragging them.

A GTK4 / libadwaita tool that shows your outputs as tiles you can drag, snaps
them flush against each other, applies the result live with `hyprctl`, and — once
you confirm — writes it back to your Hyprland config.

Built for [Omarchy](https://omarchy.org/), which configures Hyprland in **Lua**,
so the config it writes is `hl.monitor({ ... })` rather than hyprlang.

[![tests](https://github.com/BlackKingBarOrg/hyprlayout/actions/workflows/tests.yml/badge.svg)](https://github.com/BlackKingBarOrg/hyprlayout/actions/workflows/tests.yml)

*[中文说明](README.zh-CN.md)*

![hyprlayout window: draggable display canvas on the left, per-display settings on the right](docs/screenshot.png)

## Why another display tool

`nwg-displays` is the usual answer on wlroots compositors, but it writes
hyprlang `monitors.conf`. Hyprland 0.56 with a Lua config needs a different
shape entirely — and it also refuses `hyprctl keyword`, which is what most tools
use to apply changes live. hyprlayout speaks the Lua dialect on both ends:

- it emits `hl.monitor({ ... })` using the field names from Hyprland's own
  `HL.MonitorSpec` stub (`/usr/share/hypr/stubs/hl.meta.lua`);
- it applies changes with `hyprctl eval`, falling back to `keyword` on older
  hyprlang builds;
- it leaves the rest of your hand-written config alone.

## Features

- **Drag to arrange.** Tiles snap to their neighbours' edges and centre lines,
  with alignment guides while you drag and no overlaps or gaps on release.
- **Keyboard nudging.** Arrow keys move the selection 10 logical pixels, Shift
  makes it 100. Snapping shrinks to half a step so a nudge always moves.
- **Per-display settings.** Enable/disable, resolution, refresh rate, scale
  (with an Auto button that reads the panel's real DPI from its EDID), rotation,
  VRR, mirroring, and exact X/Y.
- **Try before you keep.** Apply takes effect immediately, then asks to keep or
  revert with a **15-second countdown that defaults to revert** — a display that
  goes black cannot lock you out.
- **Careful writes.** Before touching `monitors.lua` you get a unified diff. The
  old file is backed up with a timestamp and replaced atomically.
- **Your config stays yours.** Only hyprlayout's own managed block is rewritten.
  The catch-all `output = ""` rule and rules for outputs that are not connected
  right now are left untouched.
- **Turn the laptop panel off, safely.** Switch the built-in display off while
  you are docked; it comes back by itself once no external display is left, with
  or without hyprlayout running. See below.
- **Profiles.** Save arrangements ("dock", "laptop only") and recognise them
  again by an output fingerprint.
- **Live refresh.** Watches Hyprland's event socket, so plugging a monitor in
  updates the canvas — without discarding edits you have not applied yet.
- **Validation.** Warns about overlaps, displays the pointer cannot reach across
  a gap, and scales that produce a fractional logical size.

## Requirements

- Hyprland (tested on 0.56; older hyprlang builds work through the fallback)
- Python 3.11+
- PyGObject with GTK 4 and libadwaita

On Arch/Omarchy: `sudo pacman -S --needed python-gobject gtk4 libadwaita`

## Install

Run it straight from a checkout — there is no build step:

```bash
git clone https://github.com/BlackKingBarOrg/hyprlayout
cd hyprlayout
./bin/hyprlayout
```

Or put it on your `PATH` and in your app launcher:

```bash
make install     # symlinks bin/hyprlayout into ~/.local/bin, installs the .desktop file
make uninstall
```

Bind it to a key in `~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + P", "Display layout", { launch = "hyprlayout" })
o.bind("SUPER + SHIFT + P", "Dock layout", "hyprlayout --apply-profile dock")
```

## Command line

Everything the GUI does is scriptable:

```bash
hyprlayout --status              # current layout, human readable
hyprlayout --dump                # current layout as JSON
hyprlayout --print-lua           # the monitors.lua block for the current layout
hyprlayout --diff                # what --save would change
hyprlayout --save                # write monitors.lua (keeps a timestamped backup)
hyprlayout --builtin off         # switch the laptop panel off (docked)
hyprlayout --builtin on          # switch it back on
hyprlayout --builtin toggle      # flip it -- handy on a keybinding
hyprlayout --save-profile dock   # save the current layout as a profile
hyprlayout --apply-profile dock  # apply a profile (no confirmation countdown)
hyprlayout --list-profiles
```

## Keyboard

| Key | Action |
| --- | --- |
| Arrows / Shift+Arrows | Move the selected display 10 / 100 logical pixels |
| Tab | Cycle the selection on the canvas |
| Ctrl+Return | Apply |
| Ctrl+S | Save to `monitors.lua` |
| Ctrl+R | Reload from Hyprland |
| Ctrl+Z | Discard changes |
| Ctrl+Q | Quit |

## Applying versus saving

Two different things happen, and hyprlayout uses both:

1. **`hyprctl eval 'hl.monitor({ … })'`** takes effect instantly but does not
   persist — `hyprctl reload` or a restart brings your config back. Apply uses
   this, which is what makes experimenting free.
2. **`~/.config/hypr/monitors.lua`** persists. Hyprland reloads it on save.

So Apply is a trial; ticking *Also write …* (or Ctrl+S) is what makes it stick.
Both paths emit the **same Lua** (`MonitorState.lua_call()`), so the diff you
preview is exactly what runs.

### Runtime dialects

Hyprland 0.56's Lua config changed the runtime interface. hyprlayout tries the
modern form first and falls back automatically:

| Operation | Lua config (0.56+) | Older hyprlang |
| --- | --- | --- |
| Apply a layout | `hyprctl eval 'hl.monitor({…})'` | `hyprctl --batch 'keyword monitor …'` |
| Locate a display | `dispatch 'hl.dsp.focus{monitor="DP-1"}'` | `dispatch focusmonitor DP-1` |
| Move the pointer | `dispatch 'hl.dsp.cursor.move{x=…, y=…}'` | `dispatch movecursor x y` |

Note that `hyprctl` exits 0 even when it refuses a request (a Lua-configured
Hyprland answers `keyword can't work with non-legacy parsers`), so acceptance has
to be read from the reply text — which is what the code does.

## Turning the laptop panel off

Switch the built-in display off in the sidebar, or run `hyprlayout --builtin off`.
It stays off **only while an external display is connected** -- unplug the
external one and the panel comes back on its own, whether or not this app is
running.

That guarantee is not something hyprlayout invents. Writing `disabled = true` for
a laptop panel into `monitors.lua` would be a trap: nothing ever removes it, so
the next time you undock you get a black machine. Omarchy already ships the
pieces to avoid that, and hyprlayout writes into them instead:

| Piece | What it does | When |
| --- | --- | --- |
| `~/.local/state/omarchy/toggles/hypr/internal-monitor-disable.lua` | holds the actual "off" rule; `require`d by the Hyprland config after `monitors.lua`, so it wins | on config load |
| `omarchy-recover-internal-monitor.service` | deletes that file when no external display is physically connected | before the graphical session |
| `omarchy-hyprland-monitor-watch` | switches the panel back on when no external output is active any more | on hotplug |

So `monitors.lua` keeps a normal *enabled* rule for the panel even while it is
switched off, because that rule is where Omarchy reads the mode, position and
scale it restores the panel with. `tests/test_omarchy_contract.py` pins this
behaviour down by driving Omarchy's own scripts against a fake `HOME`.

On a Hyprland install without Omarchy, hyprlayout falls back to writing
`disabled = true` into `monitors.lua` and the sidebar says so: there is nothing to
switch the panel back on for you, so re-enable it before you undock.

## Logical pixels

Hyprland positions monitors in *logical* pixels: the mode is rotated by
`transform`, then divided by `scale`. A 3200×2000 panel at scale 2 occupies
1600×1000, so a 3440×1440 monitor at scale 1 sits flush at `x = 1600`. Every
number on the canvas and in the position fields is in that space.

A scale that yields a fractional logical size (3200 / 1.3, say) gets nudged by
Hyprland; the banner tells you when that will happen. The **Auto** button next to
Scale computes the panel's real DPI from the physical size in its EDID and
prefers scales that divide evenly.

## Project layout

```
hyprlayout/
├── bin/hyprlayout        # run from a checkout, no install needed
├── hyprlayout/
│   ├── model.py          # Mode / MonitorState / Rect: geometry, hyprctl parsing, Lua rendering
│   ├── hypr.py           # hyprctl calls, dialect fallbacks, socket2 event listener
│   ├── snapping.py       # edge snapping, collision push-out, validation, auto-arrange
│   ├── luawriter.py      # monitors.lua rendering, merging, diffing, backed-up writes
│   ├── profiles.py       # named layout profiles (JSON)
│   ├── canvas.py         # the draggable canvas (DrawingArea + Cairo)
│   ├── window.py         # main window and sidebar
│   ├── app.py            # Adw.Application
│   └── cli.py            # command line entry point
└── tests/                # 112 tests, stdlib unittest only
```

## Tests

```bash
make test     # python3 -m unittest discover -t . -s tests
```

- The logic layers (geometry, snapping, Lua writing, profiles) need no display.
- `test_canvas.py` drives the real drag pipeline — press, move, release, arrow
  nudges, collision push-out, redraw in both themes. It needs a display and
  skips without one.
- `test_window.py` reads the real `hyprctl monitors` to check the dirty/Apply
  logic, the validation banner and sidebar wiring. It is read-only: it never
  applies a layout or writes a file.
- Without PyGObject installed, the GTK suites skip instead of failing, so the
  core tests still run anywhere.

## Known limits

- `hyprctl` changes only affect the running instance; persisting across sessions
  means writing the config file.
- Disconnected outputs do not appear in the UI (`hyprctl monitors all` does not
  report them). Their rules in `monitors.lua` are preserved untouched.
- HDR, ICC and colour-management fields of `HL.MonitorSpec` are not exposed yet;
  lines you wrote for them are left alone.

## Contributing

Bug reports and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md)
for how to run the tests and what to include in a report.

## License

MIT — see [LICENSE](LICENSE).
