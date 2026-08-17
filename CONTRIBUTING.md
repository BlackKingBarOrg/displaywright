# Contributing

Thanks for looking. This is a small, dependency-light project and the goal is to
keep it that way.

## Getting set up

No build step and no virtualenv needed — the app runs from a checkout:

```bash
git clone https://github.com/BlackKingBarOrg/hyprlayout
cd hyprlayout
./bin/hyprlayout
```

You need Python 3.11+, `hyprctl`, and PyGObject with GTK 4 and libadwaita
(`python-gobject gtk4 libadwaita` on Arch).

## Tests

```bash
make test          # python3 -m unittest discover -t . -s tests
```

Standard-library `unittest` only — please do not add pytest or other test
dependencies.

Three tiers, and it matters which one your change belongs in:

| Suite | Needs | Notes |
| --- | --- | --- |
| `test_model`, `test_snapping`, `test_luawriter`, `test_profiles`, `test_hypr` | nothing | pure logic and mocked `hyprctl` |
| `test_canvas` | a display | drives the real drag gesture pipeline |
| `test_window` | a display **and** a running Hyprland | read-only against the live compositor |

Suites that cannot run must **skip**, never fail: the GTK imports are guarded so
the suite still passes on a machine without PyGObject. Keep it that way.

Tests must not depend on the developer's actual monitor arrangement. If you need
a particular layout, build it in the test (see
`test_window.test_normalize_moves_the_layout_to_the_origin`).

Tests must never apply a layout or write to a real config file. The one exception
is `test_hypr.test_identity_apply_is_accepted_and_changes_nothing`, which applies
the layout that is *already* live and asserts nothing changed.

## Lint

```bash
ruff check .       # config lives in pyproject.toml
```

CI runs the same command with a pinned ruff version. Rules of thumb baked into
the config: 110-column lines, and `×` in user-facing strings is deliberate
(`RUF001` is off).

## Things worth knowing before you change behaviour

- **Two runtime dialects.** Hyprland 0.56 with a Lua config refuses
  `hyprctl keyword` and wants `hyprctl eval` with Lua; older hyprlang builds have
  no `eval`. `hypr.apply_states()` and `hypr.dispatch()` try the modern form and
  fall back. If you add a new compositor interaction, follow that pattern.
- **`hyprctl` exits 0 even when it refuses a request.** Success has to be judged
  from the reply text; see `hypr._accepted()`.
- **One Lua renderer.** `MonitorState.lua_call()` produces both what gets applied
  live and what gets written to `monitors.lua`, so the previewed diff is exactly
  what runs. Please do not fork that.
- **Never clobber hand-written config.** `luawriter.merge()` only rewrites
  hyprlayout's managed block, preserves the catch-all `output = ""` rule and
  rules for outputs that are not currently connected, backs the file up with a
  timestamp, and writes atomically.
- **Applying must stay reversible.** The keep-or-revert countdown defaults to
  revert. Anything that changes what the user sees should be recoverable without
  a working screen.
- **Logical pixels everywhere.** Positions are post-transform, post-scale. If you
  are dealing in device pixels, convert at the boundary.

## Reporting a bug

Please include the output of:

```bash
hyprctl version
hyprctl monitors all -j
hyprlayout --status
```

For anything about generated config, `hyprlayout --diff` is usually the fastest
way to show what the tool wanted to write.

## Commits and pull requests

- Explain *why* in the commit message, not just what.
- Keep the test suite green, and add tests for behaviour you fix or add.
- Small, focused pull requests get reviewed faster than large ones.
