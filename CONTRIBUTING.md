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
it.

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

## Tests

```bash
make test          # python3 -m unittest discover -t . -s tests
make lint          # bytecode + type-checked QML
```

| Suite | Needs | Notes |
|---|---|---|
| `test_model`, `test_hypr`, `test_displays_*` (logic), `test_wallpapers_*` (logic), `test_migrate` | nothing | pure logic and mocked `hyprctl`; must stay importable without PyGObject |
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

## Working on the renderer

`make lint` type-checks the QML against Quickshell's and Omarchy's real modules,
which catches most mistakes before they reach a screen. What it cannot catch is
the transition state machine in `plugin/Surface.qml`; that one is worth reading
carefully before changing, in particular the comment about assignment order in
`adopt()`.

The renderer is installed as a symlink to your checkout, and Omarchy's plugin
watcher does not follow symlinks, so QML edits do not hot-reload. Run
`omarchy-restart-shell` to pick them up.

## Reporting a bug

Please include:

- `displaywright --version`, `hyprctl version`, and whether your Hyprland config
  is Lua or hyprlang;
- `displaywright outputs` and `displaywright layout status`;
- for wallpaper problems, `displaywright wallpaper status` and
  `displaywright renderer status`;
- what you expected and what happened instead.
