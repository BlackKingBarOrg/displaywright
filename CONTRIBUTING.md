# Contributing

Thanks for looking. Bug reports and pull requests are both welcome.

## Running from a checkout

No build step and no virtualenv needed — the app runs from a checkout:

```bash
git clone https://github.com/BlackKingBarOrg/displaywright
cd displaywright
./bin/displaywright
```

You need Python 3.11+ and PyGObject with GTK 4 and libadwaita
(`python-gobject gtk4 libadwaita` on Arch). To see a wallpaper on screen you
also need the renderer installed — `make plugin`, and `make unplugin` to undo
it. It draws on top of `omarchy.background` rather than replacing it, so
installing it is reversible and changes nothing until a display is pinned.

## The three halves

| | Lives in | Runs in |
|---|---|---|
| Shared core | `displaywright/*.py` | one process, Python + GTK 4 |
| The arrangement page | `displaywright/displays/` | the same process |
| The wallpaper page | `displaywright/wallpapers/` | the same process |
| The renderer | `plugin/` | inside `omarchy-shell`, QML |

The two pages are not two apps in a trench coat. They share
`displaywright/model.py` (one `MonitorState`, one geometry), `hypr.py` (one
reader, one event socket), `canvas.py` (one view transform and one hit test) and
`session.py` (one output list, one selection). A change that would make the two
pages disagree about where a display is belongs in the shared layer, not in one
page.

The renderer only meets the app at `~/.config/displaywright/wallpapers.json`,
which the window writes atomically and the plugin watches. Anything that changes
the shape of that file has to change both sides, and
`displaywright/wallpapers/preview.py` too — the window draws its preview from
that module, and the claim that the preview matches the screen only holds if it
agrees with `plugin/renderers/ImageLayer.qml`.

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
│   ├── app.py  cli.py  migrate.py
│   ├── displays/             # snapping, luawriter, omarchy, profiles,
│   │                         # the draggable canvas, the arrangement page
│   └── wallpapers/           # model, store, preview, span, library, plugin,
│                             # shell, the preview canvas, the wallpaper page
├── plugin/                   # the QML renderer, published as a repo of its own
└── tests/                    # stdlib unittest only
```

## Runtime dialects

Hyprland 0.56's Lua config changed the runtime interface, and `hyprctl` exits 0
even when it refuses a request — a Lua-configured Hyprland answers `keyword
can't work with non-legacy parsers` — so acceptance has to be read off the reply
text. `hypr.py` tries the modern form first and falls back:

| Operation | Lua config (0.56+) | Older hyprlang |
| --- | --- | --- |
| Apply a layout | `hyprctl eval 'hl.monitor({…})'` | `hyprctl --batch 'keyword monitor …'` |
| Locate a display | `dispatch 'hl.dsp.focus{monitor="DP-1"}'` | `dispatch focusmonitor DP-1` |
| Move the pointer | `dispatch 'hl.dsp.cursor.move{x=…, y=…}'` | `dispatch movecursor x y` |

## Tests

```bash
make test          # python3 -m unittest discover -t . -s tests
make lint          # bytecode + type-checked QML
```

| Suite | Needs | Notes |
|---|---|---|
| `test_model`, `test_hypr`, `test_displays_*` (logic), `test_wallpapers_*` (logic), `test_migrate`, `test_plugin_spec` | nothing | pure logic and mocked `hyprctl`; must stay importable without PyGObject |
| `test_gui_imports` | PyGObject | skips itself when GTK is missing |
| `test_canvas` | a display | drives the real drag gesture pipeline |
| `test_displays_page` | a display **and** a running Hyprland | read-only against the live compositor |

Suites that cannot run must **skip**, never fail: the GTK imports are guarded so
the suite still passes on a machine without PyGObject. Keep it that way.

Tests must not depend on the developer's actual monitor arrangement. If you need
a particular layout, build it in the test (see
`test_displays_page.test_normalize_moves_the_layout_to_the_origin`).

Nothing in the suite may touch `~/.config`, `~/.cache`, `~/Pictures`, restart the
shell, apply a layout or change a wallpaper. Building the window builds both
pages, and the wallpaper page creates directories the moment it exists — so
every window test redirects `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`,
`XDG_STATE_HOME` and `XDG_PICTURES_DIR` into a temporary root first. `WindowFixture`
in `tests/test_displays_page.py` and the setup in `tests/test_migrate.py` are the
patterns to copy.

The one exception is `test_hypr.test_identity_apply_is_accepted_and_changes_nothing`,
which applies the layout that is *already* live and asserts nothing changed.

## Working on the renderer's manifest

`tests/test_plugin_spec.py` mirrors Omarchy's plugin contract by hand — the
rules in `shell/services/PluginRegistry.qml` and `bin/omarchy-plugin-validate`.
It does that so a manifest a user's shell would reject fails on a runner with
no Omarchy installed. When Omarchy *is* installed the same suite also shells
out to the real `omarchy-plugin-validate`, and `make validate-plugin` runs it
directly. If Omarchy changes the contract, that test file is what has to change
with it.

`plugin/` is published as a repository root of its own (`make publish-plugin`),
so its `README.md` and `LICENSE` are part of the deliverable, not decoration.

## Working on the renderer

`make lint` type-checks the QML against Quickshell's and Omarchy's real modules,
which catches most mistakes before they reach a screen. What it cannot catch is
the transition state machine in `plugin/Surface.qml`; that one is worth reading
carefully before changing, in particular the comment about assignment order in
`adopt()`.

The renderer is installed as a symlink to your checkout, and Omarchy's plugin
watcher does not follow symlinks, so QML edits do not hot-reload. Run
`omarchy-restart-shell` to pick them up.

## Publishing the renderer

`omarchy plugin add <url>` clones a repository straight into
`~/.config/omarchy/plugins/<id>/`, so `manifest.json` has to sit at a repository
root. Ours is in `plugin/`, deliberately next to the `preview.py` whose
arithmetic it has to stay in step with — two hand-maintained repositories is how
a preview starts lying about what the screen will do. The subtree is split out
on publish instead:

```bash
make publish-plugin      # validate, test, git subtree split --prefix=plugin, push
```

The result, [displaywright-shell-plugin][mirror], is a **generated mirror**.
Never commit to it directly; the next publish force-pushes over it.

To list it on [omarchyplugins.com](https://omarchyplugins.com), open their issue
form with the mirror's link, a category and tags. Their automated check
validates the current commit before a maintainer approves the listing.

[mirror]: https://github.com/BlackKingBarOrg/displaywright-shell-plugin

## Reporting a bug

Please include:

- `displaywright --version`, `hyprctl version`, and whether your Hyprland config
  is Lua or hyprlang;
- `displaywright outputs` and `displaywright layout status`;
- for wallpaper problems, `displaywright wallpaper status` and
  `displaywright renderer status`;
- what you expected and what happened instead.
