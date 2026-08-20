# displaywright

Where your displays are, and what is drawn on them. One window.

A GTK4 / libadwaita tool for [Omarchy](https://omarchy.org/) and Hyprland with
two halves that share a picture of your desk:

- **Displays** — drag your outputs into place, snap them flush, set resolution,
  refresh rate, scale and rotation. Applied live with `hyprctl`, then written
  back to your Lua `monitors.lua`.
- **Wallpapers** — a different picture on each display, with every fit Windows
  has. Drawn by an `omarchy-shell` plugin that replaces the built-in background
  renderer, so there is only ever one surface per output.

[![tests](https://github.com/BlackKingBarOrg/displaywright/actions/workflows/tests.yml/badge.svg)](https://github.com/BlackKingBarOrg/displaywright/actions/workflows/tests.yml)

*[中文说明](README.zh-CN.md)*

![the Displays page: a draggable display canvas on the left, per-display settings on the right](docs/screenshot-displays.png)

![the Wallpapers page: the same arrangement with each display's wallpaper drawn into it, fit controls below, and the picture library underneath](docs/screenshot-wallpapers.png)

## Why one app

They are the same question asked twice. Both halves need the output list, both
need its geometry in logical pixels, both draw the desk as a set of rectangles
you click on, and both watch Hyprland's event socket for a monitor being
plugged in. Run them as two programs and you get two answers: the wallpaper
tool showing a display in the position the arrangement tool has already moved
it out of.

Here there is one `hyprctl` reader, one event listener, one geometry model and
one canvas. Pick a display on either page and it stays picked on the other.
Drag it somewhere new and the wallpaper preview follows it there — with a note
saying the arrangement is not applied yet, because it isn't.

It also settled an argument the two tools had been having. `hyprctl` reports a
rotated display's **mode**, not the size the panel shows: a portrait 2560×1440
is still reported `2560x1440`. One of the two tools rotated that number before
using it, inventing a `1440x2560` mode no display advertises. Merging them made
the disagreement impossible to keep.

## Displays

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
- **Your config stays yours.** Only displaywright's own managed block is
  rewritten. The catch-all `output = ""` rule and rules for outputs that are not
  connected right now are left untouched.
- **Turn the laptop panel off, safely.** Switch the built-in display off while
  you are docked; it comes back by itself once no external display is left, with
  or without this app running. See below.
- **Profiles.** Save arrangements ("dock", "laptop only") and recognise them
  again by an output fingerprint.
- **Validation.** Warns about overlaps, displays the pointer cannot reach across
  a gap, and scales that produce a fractional logical size.

### Why not nwg-displays

`nwg-displays` is the usual answer on wlroots compositors, but it writes
hyprlang `monitors.conf`. Hyprland 0.56 with a Lua config needs a different
shape entirely — and it also refuses `hyprctl keyword`, which is what most tools
use to apply changes live. displaywright speaks the Lua dialect on both ends:

- it emits `hl.monitor({ ... })` using the field names from Hyprland's own
  `HL.MonitorSpec` stub (`/usr/share/hypr/stubs/hl.meta.lua`);
- it applies changes with `hyprctl eval`, falling back to `keyword` on older
  hyprlang builds;
- it leaves the rest of your hand-written config alone.

## Wallpapers

Omarchy draws the desktop background from inside `omarchy-shell`, and that
renderer shows **one image on every display, always cropped to fill**. There is
no per-display picture and no choice of fit. displaywright replaces that
renderer with one that takes both.

- **A picture per display.** Displays you have not touched keep following the
  Omarchy theme background, so a fresh install looks exactly like stock Omarchy.
- **Every fit Windows has**, and they behave the way Windows' do — including on
  a scaled display, which is where most tools get Center and Tile wrong.
- **A preview that is not a guess.** The arrangement at the top of the page is
  the same canvas the Displays page draws, and each picture goes through the
  same arithmetic the renderer runs — so you can see what Center will do before
  you commit to it.
- **Span across displays**, cut from your actual layout, and honest about the
  cost when your displays are not flush.
- **One folder, holding what you chose.** Everything you pick is copied into
  `~/Pictures/Displaywright`, and that folder is what the grid shows. The
  wallpaper survives you emptying `~/Downloads`, and the grid does not fill up
  with screenshots.
- **Flat colours** as well as pictures.
- **Changes apply as you make them.** No Apply button on this page; a wallpaper
  is visible the moment it lands and costs nothing to undo. (The Displays page
  is the opposite on purpose: a bad wallpaper is an eyesore, a bad arrangement
  is a black screen you cannot click your way out of.)
- **The theme keeps working.** `omarchy-theme-bg-set`, the SUPER + CTRL + SPACE
  background switcher and full theme switches all behave as before, palette
  transition included.

### Why not swaybg / hyprpaper / waypaper

**swaybg, hyprpaper and wpaperd** each want to own the background themselves.
Omarchy's shell already owns it, and it also owns the theme switch — the IPC
call that recolours the entire shell rides along with the background transition.
Bolting a second background daemon on top means either two surfaces fighting
over one Wayland layer, or a broken theme switch. **waypaper** is a front-end
for exactly those daemons, so it inherits the problem.

displaywright goes the other way: it *is* the background renderer, installed as
an ordinary Omarchy shell plugin.

### The fits

| displaywright | Windows | What it does |
|---|---|---|
| `fill` | Fill | Scales until the display is covered, crops the overflow. The default. |
| `fit` | Fit | Scales until the whole picture is visible, backdrop in the bars. |
| `stretch` | Stretch | Ignores the aspect ratio and distorts to fit exactly. |
| `tile` | Tile | Repeats the file at its own resolution from the top-left corner. |
| `center` | Center | Draws the file at its own resolution in the middle, backdrop around it. |
| `span` | Span | One picture across every display at once. |

**Center and Tile are defined in device pixels**, not layout pixels. On a
200%-scaled laptop panel — 3200×2000 physical, 1600×1000 logical — an 800×600
file centred by displaywright covers 800×600 real pixels, the same as it would
on Windows. Tools that skip the conversion draw it at double size.

### Span, and what it costs

Span stretches one picture over the bounding box of every display and gives each
one the slice it sits on. That is only lossless when your displays are flush.
These two are not:

```
eDP-1  1600×1000 at 0,56       bounding box 4160×1882
DP-1   2560×1440 at 1600,-826  68% of the picture lands on a screen
```

The other 32% falls in the gap between the panels, where nothing can draw it.
displaywright tells you the number rather than letting you find out. The
geometry is recomputed by the renderer from the live display list, so moving a
display re-cuts the picture whether or not the window is open.

## Requirements

- Hyprland (tested on 0.56; older hyprlang builds work through the fallback)
- Omarchy 4.x with `omarchy-shell` (Quickshell) — for the wallpaper renderer
- Python 3.11+
- PyGObject with GTK 4 and libadwaita
- `qt6-multimedia-ffmpeg` for video wallpapers, `ffmpeg` for their thumbnails

On Arch/Omarchy: `sudo pacman -S --needed python-gobject gtk4 libadwaita`

The Displays half works on any Hyprland. Only the wallpaper renderer needs
Omarchy.

## Install

Run it straight from a checkout — there is no build step:

```bash
git clone https://github.com/BlackKingBarOrg/displaywright
cd displaywright
./bin/displaywright
```

Or put it on your `PATH` and in your app launcher:

```bash
make install     # symlinks bin/displaywright into ~/.local/bin, installs the .desktop file
make plugin      # the wallpaper renderer, into omarchy-shell
make uninstall
```

`make plugin` is a separate step because it changes which plugin owns the
desktop background. It is reversible with `make unplugin`.

If you only want the wallpaper renderer and not the window, the plugin is also
published on its own for `omarchy plugin add` — see
[Just the renderer](#just-the-renderer).

Bind it to a key in `~/.config/hypr/bindings.lua`:

```lua
o.bind("SUPER + P", "Displays and wallpapers", { launch = "displaywright" })
o.bind("SUPER + SHIFT + P", "Dock layout", "displaywright layout profile-apply dock")
```

### Coming from wallwright or hyprlayout

displaywright is those two tools merged. One command moves everything over:

```bash
displaywright migrate
```

It moves `~/Pictures/Wallwright` to `~/Pictures/Displaywright` and rewrites the
paths that point into it, moves `~/.config/wallwright/config.json` to
`~/.config/displaywright/wallpapers.json`, moves `~/.config/hyprlayout/profiles.json`
and the thumbnail cache, then installs the new renderer and clears wallwright's
out of `shell.json` — two plugins on the background layer is a coin flip per
session. It refuses to overwrite anything that already exists, and running it
twice does nothing.

Until you run it, an existing `~/.config/wallwright/config.json` is still read,
so nothing disappears in the meantime. A `monitors.lua` carrying hyprlayout's
managed block is recognised and rewritten in place rather than gaining a second
block underneath.

### Just the renderer

The wallpaper half is an ordinary Omarchy shell plugin, published on its own so
that `manifest.json` sits at a repository root — which is what
`omarchy plugin add` requires:

```bash
omarchy plugin add https://github.com/BlackKingBarOrg/displaywright-shell-plugin.git --enable
omarchy plugin disable omarchy.background
```

That second line is not optional and `omarchy plugin add` will not do it for
you; see below for why. You then configure it by hand in
`~/.config/displaywright/wallpapers.json`, since the picker lives in the window.
`make plugin` (or `displaywright renderer install`) does both steps at once from
this checkout, which is the easier path if you want the window anyway.

That repository is generated from `plugin/` here by `make publish-plugin`, so
issues and pull requests belong on this repo.

### What installing the renderer changes

Two files, both minimally:

- `~/.config/omarchy/plugins/ai.bkblab.displaywright` — a symlink to this checkout.
- `~/.config/omarchy/shell.json` — `ai.bkblab.displaywright` is added to
  `plugins[]`, and `omarchy.background` is added to `disabledPlugins[]`.
  Nothing else in the file is touched, your bar layout included.

Disabling `omarchy.background` is not optional. Both plugins put an opaque
surface on `WlrLayer.Background`, and Wayland defines no order between two
surfaces on the same layer — leaving both enabled means the wallpaper you get is
a coin flip per session.

Displacing it means inheriting its second job. Omarchy's theme switch calls
`background themeTransition`, and that call is the only thing that applies the
new palette to the running shell. displaywright implements the whole
`background` IPC target, palette included, so a theme switch still recolours
everything. `displaywright renderer uninstall` puts it all back.

## Command line

Everything the window does is scriptable.

```bash
displaywright                       # open the window
displaywright outputs               # the displays Hyprland reports
```

```bash
displaywright layout status              # current arrangement, human readable
displaywright layout dump                # as JSON
displaywright layout lua                 # the monitors.lua block for it
displaywright layout diff                # what `layout save` would change
displaywright layout save                # write monitors.lua (timestamped backup)
displaywright layout builtin off         # switch the laptop panel off (docked)
displaywright layout builtin on
displaywright layout builtin toggle      # flip it -- handy on a keybinding
displaywright layout profiles            # list saved profiles
displaywright layout profile-save dock
displaywright layout profile-apply dock  # no confirmation countdown
displaywright layout profile-delete dock
```

```bash
displaywright wallpaper status
displaywright wallpaper set DP-1 ~/Downloads/a.jpg              # copies it in, keeps the fit
displaywright wallpaper set DP-1 ~/Downloads/a.jpg --fit tile
displaywright wallpaper set eDP-1 ~/a.png --fit fit --backdrop '#101820'
displaywright wallpaper set span ~/Pictures/wide.jpg            # across every display
displaywright wallpaper set DP-1 /mnt/big.jpg --no-copy         # leave it where it is
displaywright wallpaper color DP-1 '#101820'
displaywright wallpaper clear DP-1                              # back to the theme background
displaywright wallpaper clear                                   # every display
```

```bash
displaywright renderer status
displaywright renderer install [--copy]   # --copy instead of symlinking
displaywright renderer uninstall
```

## Keyboard

| Key | Action |
| --- | --- |
| Arrows / Shift+Arrows | Move the selected display 10 / 100 logical pixels |
| Tab | Cycle the selection on the canvas |
| Ctrl+Return | Apply the arrangement |
| Ctrl+S | Save to `monitors.lua` |
| Ctrl+R | Re-read displays from Hyprland |
| Ctrl+Z | Discard arrangement changes |
| Ctrl+O | Open the wallpaper folder |
| Ctrl+Q | Quit |

## Applying versus saving

For the arrangement, two different things happen and displaywright uses both:

1. **`hyprctl eval 'hl.monitor({ … })'`** takes effect instantly but does not
   persist — `hyprctl reload` or a restart brings your config back. Apply uses
   this, which is what makes experimenting free.
2. **`~/.config/hypr/monitors.lua`** persists. Hyprland reloads it on save.

So Apply is a trial; ticking *Also write …* (or Ctrl+S) is what makes it stick.
Both paths emit the **same Lua** (`MonitorState.lua_call()`), so the diff you
preview is exactly what runs.

Wallpapers have no equivalent split: the config file is the only state, and the
renderer watches it.

### Runtime dialects

Hyprland 0.56's Lua config changed the runtime interface. displaywright tries
the modern form first and falls back automatically:

| Operation | Lua config (0.56+) | Older hyprlang |
| --- | --- | --- |
| Apply a layout | `hyprctl eval 'hl.monitor({…})'` | `hyprctl --batch 'keyword monitor …'` |
| Locate a display | `dispatch 'hl.dsp.focus{monitor="DP-1"}'` | `dispatch focusmonitor DP-1` |
| Move the pointer | `dispatch 'hl.dsp.cursor.move{x=…, y=…}'` | `dispatch movecursor x y` |

Note that `hyprctl` exits 0 even when it refuses a request (a Lua-configured
Hyprland answers `keyword can't work with non-legacy parsers`), so acceptance has
to be read from the reply text — which is what the code does.

## Turning the laptop panel off

Switch the built-in display off in the sidebar, or run
`displaywright layout builtin off`. It stays off **only while an external
display is connected** — unplug the external one and the panel comes back on its
own, whether or not this app is running.

That guarantee is not something displaywright invents. Writing `disabled = true`
for a laptop panel into `monitors.lua` would be a trap: nothing ever removes it,
so the next time you undock you get a black machine. Omarchy already ships the
pieces to avoid that, and displaywright writes into them instead:

| Piece | What it does | When |
| --- | --- | --- |
| `~/.local/state/omarchy/toggles/hypr/internal-monitor-disable.lua` | holds the actual "off" rule; `require`d by the Hyprland config after `monitors.lua`, so it wins | on config load |
| `omarchy-recover-internal-monitor.service` | deletes that file when no external display is physically connected | before the graphical session |
| `omarchy-hyprland-monitor-watch` | switches the panel back on when no external output is active any more | on hotplug |

So `monitors.lua` keeps a normal *enabled* rule for the panel even while it is
switched off, because that rule is where Omarchy reads the mode, position and
scale it restores the panel with. `tests/test_displays_omarchy_contract.py` pins
this behaviour down by driving Omarchy's own scripts against a fake `HOME`.

On a Hyprland install without Omarchy, displaywright falls back to writing
`disabled = true` into `monitors.lua` and the sidebar says so: there is nothing
to switch the panel back on for you, so re-enable it before you undock.

## Logical pixels

Hyprland positions monitors in *logical* pixels: the mode is rotated by
`transform`, then divided by `scale`. A 3200×2000 panel at scale 2 occupies
1600×1000, so a 2560×1440 monitor at scale 1 sits flush at `x = 1600`. Every
number on the canvas and in the position fields is in that space, and so is the
span arithmetic — which is what makes it line up with what Quickshell's
`ShellScreen` reports inside the renderer.

Both canvases draw rectangles at that logical size, because that is what makes
the positions, the gaps and the span preview truthful. The captions on the
Wallpapers page name each display's **real** resolution instead — the pixels a
wallpaper has to cover — and mark a rotated one with `↻`. On a 200%-scaled
laptop panel the two differ by a factor of two, so both are worth having.

A scale that yields a fractional logical size (3200 / 1.3, say) gets nudged by
Hyprland; the banner tells you when that will happen. The **Auto** button next to
Scale computes the panel's real DPI from the physical size in its EDID and
prefers scales that divide evenly.

## Your wallpaper folder

`~/Pictures/Displaywright`, created on first run. (More precisely:
`Displaywright` inside whatever `XDG_PICTURES_DIR` points at.) It is the
**only** folder the grid shows until you add another, and **Open wallpaper
folder** in the menu opens it.

Choosing a file from anywhere the picker does not already look — a download, a
`/tmp` scratch file, a shared drive — copies it in and points the wallpaper at
the copy. That is the whole reason the folder exists, and it does two jobs at
once: a wallpaper that breaks when you clear out `~/Downloads` is not much of a
wallpaper, and a grid built from the whole of `~/Pictures` is mostly
screenshots.

**Add folder…** in the menu brings in a collection you already keep somewhere
else; files inside it are then used where they lie rather than copied.

Copying is careful about not accumulating junk:

- A file the picker already sees is left where it is, so clicking a thumbnail
  never clones it.
- A file whose contents are already in the folder resolves to that copy, so
  picking the same download twice does not make a second one.
- A different file with a name already taken becomes `name-2.ext`.
- The copy is written under a temporary name and renamed into place, so a
  half-written file is never offered as a wallpaper.

`wallpaper set --no-copy` opts out for one call, and the original is always left
untouched either way.

## The config files

Both live in `~/.config/displaywright/`.

`wallpapers.json` is watched by the renderer, so editing it by hand works;
writes are atomic so a half-written file can never reach the screen.

```json
{
  "version": 1,
  "monitors": {
    "eDP-1": { "kind": "image", "path": "/home/you/a.jpg", "fit": "fill" },
    "DP-1":  { "kind": "image", "path": "/home/you/b.png", "fit": "center",
               "backdrop": "#101820" }
  },
  "span": null,
  "folders": ["/home/you/Pictures/Wallpapers"]
}
```

An output that is absent follows the theme background. `span`, when set, wins
over every entry in `monitors`. `folders` is only read by the picker. Anything
unparseable is dropped rather than raised on — a mangled entry costs you that
wallpaper, never your desktop.

`profiles.json` holds the named arrangements, each with a fingerprint of the
outputs it was saved against.

## Live wallpapers

The point of building the renderer this way is that the surface it draws into
can hold more than a picture. Each source has a `kind` and the renderer
dispatches on it, so the rest is one QML file per format.

| kind | Status |
|---|---|
| `image` | Done, and what everything above describes. |
| `color` | Done. |
| `video` | Implemented (`MediaPlayer`, looping, muted, pauses under a fullscreen window). Type-checks clean but **not yet run on hardware** — treat it as untested. |
| `web` | Not started. `WebEngineView` on the background surface; this is what Wallpaper Engine's "web" wallpapers are underneath. |
| `shader` | Not started. `ShaderEffect` running a fragment shader, for Shadertoy-style backgrounds. |

Wallpaper Engine's own `.pkg` scene format is deliberately out of scope. It is a
proprietary binary format, and the reverse-engineered player for it needs you to
own Wallpaper Engine on Steam. A `kind` could be added for it later without
changing anything else here.

## Project layout

```
displaywright/
├── bin/displaywright         # run from a checkout, no install needed
├── displaywright/
│   ├── model.py              # Mode / MonitorState / Rect: geometry, hyprctl parsing, Lua rendering
│   ├── hypr.py               # hyprctl calls, dialect fallbacks, socket2 event listener
│   ├── paths.py              # XDG roots and atomic-write helpers
│   ├── session.py            # the shared state both pages read
│   ├── canvas.py             # the desk drawn small: view maths, hit testing, selection
│   ├── drawing.py            # cairo helpers both canvases use
│   ├── window.py             # one window, two pages
│   ├── app.py                # Adw.Application
│   ├── cli.py                # command line entry point
│   ├── migrate.py            # wallwright / hyprlayout -> displaywright
│   ├── displays/
│   │   ├── snapping.py       # edge snapping, collision push-out, validation, auto-arrange
│   │   ├── luawriter.py      # monitors.lua rendering, merging, diffing, backed-up writes
│   │   ├── omarchy.py        # the built-in-panel toggle
│   │   ├── profiles.py       # named arrangement profiles (JSON)
│   │   ├── canvas.py         # the draggable arrangement
│   │   └── page.py           # canvas plus per-display sidebar
│   └── wallpapers/
│       ├── model.py          # Fit / Kind / Source / Config
│       ├── store.py          # wallpapers.json, atomically
│       ├── preview.py        # where a picture lands, for each fit
│       ├── span.py           # one picture across the whole desk
│       ├── library.py        # the picture folder, thumbnails, copying files in
│       ├── plugin.py         # installing the renderer into omarchy-shell
│       ├── shell.py          # omarchy-shell IPC
│       ├── canvas.py         # the arrangement, with the wallpapers on it
│       └── page.py           # canvas, fit controls, picture library
├── plugin/                   # the QML renderer, running inside omarchy-shell
│   ├── manifest.json         # the Omarchy plugin contract, schemaVersion 1
│   ├── Wallpaper.qml         # entry point: one surface per output, config watching
│   ├── Surface.qml           # one output's surface, transitions, IPC
│   ├── renderers/            # one file per source kind: image, color, video
│   └── README.md, LICENSE, preview.png   # published as a repo root of its own
└── tests/                    # 290 tests, stdlib unittest only
```

## Tests

```bash
make test             # python3 -m unittest discover -t . -s tests
make lint             # bytecode-compiles the Python, type-checks the QML against
                      # Quickshell's and Omarchy's real modules
make validate-plugin  # runs Omarchy's own omarchy-plugin-validate on plugin/
make run              # the window, straight from the checkout
```

- The logic layers (geometry, snapping, Lua writing, profiles, fits, spans,
  plugin installation, migration) need no display and no compositor.
- `test_canvas.py` drives the real drag pipeline — press, move, release, arrow
  nudges, collision push-out, redraw in both themes.
- `test_displays_page.py` builds the whole window against the live `hyprctl
  monitors` to check the dirty/Apply logic, the validation banner and the
  sidebar wiring. It is read-only: it never applies a layout, and every XDG root
  is redirected into a temporary directory first.
- `test_plugin_spec.py` re-implements Omarchy's plugin contract — the manifest
  rules from `PluginRegistry.qml` and `omarchy-plugin-validate` — so a manifest
  that a user's shell would reject fails here first, on a runner with no
  Omarchy on it. When Omarchy *is* present it also runs the real validator.
- Without PyGObject installed, the GTK suites skip instead of failing, so the
  core tests still run anywhere.

## Known limits

- `hyprctl` changes only affect the running instance; persisting across sessions
  means writing the config file.
- Disconnected outputs do not appear in the UI (`hyprctl monitors all` does not
  report them). Their rules in `monitors.lua` are preserved untouched.
- HDR, ICC and colour-management fields of `HL.MonitorSpec` are not exposed yet;
  lines you wrote for them are left alone.
- The renderer is installed as a symlink to your checkout, and Omarchy's plugin
  watcher does not follow symlinks, so QML edits do not hot-reload. Run
  `omarchy-restart-shell` to pick them up.

## Publishing the renderer

`omarchy plugin add <url>` clones a repository straight into
`~/.config/omarchy/plugins/<id>/`, so `manifest.json` has to sit at a repository
root. Ours lives in `plugin/`, next to the `preview.py` whose arithmetic it has
to stay in step with — splitting them into two hand-maintained repositories is
how a preview starts lying about what the screen will do. So the subtree is
split out on publish instead:

```bash
make publish-plugin      # validate, test, git subtree split --prefix=plugin, push
```

The result is a **generated mirror**. Never commit to it directly; the next
publish force-pushes over it.

To list it on [omarchyplugins.com](https://omarchyplugins.com), the community
directory, open their issue form with the plugin repository's link, a category
and tags. Their automated check validates the current commit before a
maintainer approves the listing.

## Contributing

Bug reports and pull requests are welcome — see [CONTRIBUTING.md](CONTRIBUTING.md)
for how to run the tests and what to include in a report.

## License

MIT — see [LICENSE](LICENSE).
