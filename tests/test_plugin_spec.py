"""The shipped plugin folder has to satisfy Omarchy's plugin contract.

`omarchy plugin add <url>` clones a repository and runs
`omarchy-plugin-validate` on it before letting it anywhere near the shell, and
the shell's own `PluginRegistry.validateManifest` refuses anything that slips
past. Both live on an Omarchy machine and neither exists on a CI runner, so the
rules are re-implemented here: a manifest that would be rejected on a user's
desktop should fail in the suite first.

Mirrors, in order: `shell/services/PluginRegistry.qml` and
`bin/omarchy-plugin-validate`. When those change, this is what has to change
with them.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest

from displaywright.wallpapers import plugin

#: The registry's own id rule, from omarchy-plugin-validate.
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")

#: A kind is a promise to supply something to load, and the shell looks for it
#: under a fixed key. Claiming a kind without its entry point installs fine and
#: then does nothing.
KIND_ENTRY_POINTS = {
    "bar": "bar",
    "bar-widget": "barWidget",
    "menu": "menu",
    "overlay": "overlay",
    "panel": "panel",
    "service": "service",
}

REQUIRED = ("id", "name", "version", "kinds", "entryPoints")

#: Required by the marketplace listing rather than by the shell.
MARKETPLACE_REQUIRED = ("author", "description")


class ManifestSpec(unittest.TestCase):
    def setUp(self):
        self.source = plugin.source_dir()
        self.manifest = json.loads((self.source / "manifest.json").read_text())

    def test_schema_version_is_the_number_one(self):
        # jq's == and QML's !== are both type-aware: the string "1" is rejected.
        self.assertIs(type(self.manifest["schemaVersion"]), int)
        self.assertEqual(self.manifest["schemaVersion"], 1)

    def test_every_required_field_is_present(self):
        for field in REQUIRED:
            with self.subTest(field=field):
                self.assertIn(field, self.manifest)

    def test_the_id_is_well_formed_and_not_reserved(self):
        plugin_id = self.manifest["id"]
        self.assertTrue(ID_RE.match(plugin_id), plugin_id)
        self.assertNotIn("..", plugin_id)
        self.assertFalse(plugin_id.startswith("omarchy."),
                         "omarchy.* is reserved for first-party plugins")

    def test_the_id_matches_the_one_the_installer_uses(self):
        self.assertEqual(self.manifest["id"], plugin.PLUGIN_ID)

    def test_kinds_is_a_non_empty_array(self):
        kinds = self.manifest["kinds"]
        self.assertIsInstance(kinds, list)
        self.assertTrue(kinds)

    def test_every_kind_has_the_entry_point_it_promises(self):
        entry_points = self.manifest["entryPoints"]
        self.assertIsInstance(entry_points, dict)
        for kind in self.manifest["kinds"]:
            key = KIND_ENTRY_POINTS.get(kind)
            if key is None:
                continue  # a kind the validator does not police
            with self.subTest(kind=kind):
                self.assertIn(key, entry_points)

    def test_entry_points_are_safe_relative_paths_that_exist(self):
        for key, value in self.manifest["entryPoints"].items():
            with self.subTest(entry_point=key):
                self.assertIsInstance(value, str)
                self.assertTrue(value)
                self.assertFalse(value.startswith("/"))
                self.assertNotIn("..", value)
                self.assertNotIn("\n", value)
                self.assertTrue((self.source / value).is_file())

    def test_no_symlinks_anywhere_in_the_plugin_folder(self):
        # A symlink could point a copied plugin back at arbitrary files once it
        # lands in the trusted plugins directory, so the validator refuses the
        # whole folder. .git is skipped: the shell never loads git's internals.
        strays = [
            path for path in self.source.rglob("*")
            if path.is_symlink() and ".git" not in path.parts
        ]
        self.assertEqual(strays, [])


class MarketplaceListing(unittest.TestCase):
    """What omarchyplugins.com asks for on top of what the shell enforces."""

    def setUp(self):
        self.source = plugin.source_dir()
        self.manifest = json.loads((self.source / "manifest.json").read_text())

    def test_author_and_description_are_filled_in(self):
        for field in MARKETPLACE_REQUIRED:
            with self.subTest(field=field):
                self.assertTrue(str(self.manifest.get(field, "")).strip())

    def test_the_version_fits_the_listing(self):
        self.assertLessEqual(len(self.manifest["version"]), 64)

    def test_the_published_folder_carries_a_readme_and_a_licence(self):
        # The plugin folder is published as a repository root of its own, so
        # these have to be inside it, not only at the top of this repo.
        for name in ("README.md", "LICENSE"):
            with self.subTest(file=name):
                self.assertTrue((self.source / name).is_file())

    def test_double_click_reaches_a_picker_that_needs_nothing_else_installed(self):
        # The entry point for someone who installed only the plugin. It has to
        # be the renderer's own script, not a command from the app: on a fresh
        # install no display is pinned and no window exists.
        surface = (self.source / "Surface.qml").read_text()
        self.assertIn("pick-wallpaper.sh", surface)
        self.assertIn("onDoubleClicked", surface)
        script = self.source / "pick-wallpaper.sh"
        self.assertTrue(script.is_file())
        self.assertTrue(script.stat().st_mode & 0o111, "picker script is not executable")
        body = script.read_text()
        # It drives Omarchy's own overlay rather than shipping a second picker.
        self.assertIn("omarchy-shell image-selector open", body)
        # A span outranks the per-display entries, so writing one under a span
        # would look like the pick did nothing.
        self.assertIn("del(.span)", body)

    def test_the_readme_leads_with_the_double_click(self):
        readme = (self.source / "README.md").read_text()
        use = readme.split("## Use", 1)[1]
        self.assertIn("Double-click", use.split("###", 1)[0])

    def test_the_readme_shows_how_to_use_the_plugin_on_its_own(self):
        # Installed from the marketplace this is the renderer and nothing else:
        # no window, no command on PATH. So the config file it reads is not an
        # appendix, it is the only way anyone can use what they just installed.
        readme = (self.source / "README.md").read_text()
        self.assertIn("wallpapers.json", readme)
        self.assertIn('"monitors"', readme)
        for fit in ("fill", "fit", "stretch", "tile", "center"):
            with self.subTest(fit=fit):
                self.assertIn(f"`{fit}`", readme)

    def test_the_readme_does_not_recommend_a_key_omarchy_already_uses(self):
        # It recommended SUPER + P for two releases. That is Omarchy's stock
        # "Pseudo window" binding (default/hypr/bindings/tiling.lua), and the
        # README did not say to unbind it first -- so anyone who copied the
        # line got a pseudo-tiled window and a plugin that looked broken.
        readme = (self.source / "README.md").read_text()
        for taken in ("SUPER + P", "SUPER + F", "SUPER + CTRL + V"):
            self.assertNotIn(f'o.bind("{taken}"', readme,
                             f"{taken} is a stock Omarchy binding")

    def test_the_readme_leads_with_the_route_that_needs_no_setup(self):
        # This said "write yourself a keybind" and nothing else for two
        # releases, and three people in a row read that as the plugin being
        # broken. The launcher entry has to be the documented way in; the
        # keybind is for people who want one.
        readme = " ".join((self.source / "README.md").read_text().split())
        self.assertIn("SUPER + ALT + SPACE", readme,
                      "the Apps menu is the only route that needs no setup")
        self.assertIn("install-shortcuts.sh", readme)
        self.assertLess(readme.index("SUPER + ALT + SPACE"),
                        readme.index("install-shortcuts.sh"),
                        "the route needing no setup should come first")

    def test_the_strip_only_offers_what_qt_can_draw(self):
        # This Qt has plugins for jpeg, gif, ico and svg on top of the built-in
        # png and bmp, and no AVIF, JPEG XL or WebP decoder -- the packaged
        # extras do not add one either. Listing such a file offers a picture
        # that draws as nothing, which is exactly how it was reported.
        script = (self.source / "list-wallpapers.sh").read_text()
        for bad in ("avif", "jxl", "webp", "heic"):
            with self.subTest(format=bad):
                self.assertNotIn(f"*.{bad}", script)
        for good in ("png", "jpg", "jpeg", "bmp", "gif"):
            with self.subTest(format=good):
                self.assertIn(f"*.{good}", script)

    def test_adding_a_picture_converts_what_qt_cannot_draw(self):
        # Refusing those formats outright would mean explaining which decoders
        # this particular Qt build happens to ship, so the chooser offers them
        # and the import converts.
        script = (self.source / "add-wallpaper.sh").read_text()
        self.assertIn("avif", script, "the chooser does not offer avif at all")
        self.assertIn("qt_can_draw", script)
        self.assertIn("convert_to_png", script)
        # And has somewhere to fall back to if ImageMagick is absent.
        self.assertIn("ffmpeg", script)

    def test_removing_a_picture_cannot_reach_outside_the_wallpaper_folder(self):
        # The strip also lists the theme's own backgrounds, and a remove that
        # took those would damage something this tool did not install.
        script = (self.source / "remove-wallpaper.sh").read_text()
        self.assertIn("Pictures/Displaywright", script)
        self.assertIn("readlink -f", script, "a path with .. would walk out")
        self.assertIn("gio trash", script, "remove should not mean gone")

    def test_the_readme_points_at_the_clicking_route(self):
        # Editing JSON is the floor, not the intended experience. Someone who
        # would rather click has to be able to find out how. That used to mean
        # pointing at a separate GTK project; the picture library is the strip
        # along the bottom of the overlay now, and the README said otherwise
        # for a release. Matched against unwrapped text: the README is
        # hard-wrapped at 80 and a phrase lands across a line break as often
        # as not.
        readme = " ".join((self.source / "README.md").read_text().split())
        self.assertIn("Double-click a display", readme)
        self.assertIn("strip along the bottom", readme)
        self.assertIn("github.com/BlackKingBarOrg/displaywright", readme)
        self.assertNotIn("separate project", readme,
                         "the picture library ships in this plugin now")

    def test_nothing_user_facing_still_claims_to_replace_the_stock_renderer(self):
        # The description is what the marketplace card shows, and it said
        # "Replaces Omarchy's built-in background renderer" for as long as that
        # was true. It draws on top of it now.
        self.assertNotIn("eplace", self.manifest["description"])

    def test_the_readme_does_not_ask_anyone_to_disable_the_stock_renderer(self):
        # The renderer draws on top of omarchy.background now. An install
        # instruction that still switches it off would blank every display the
        # user has not given a wallpaper to.
        readme = (self.source / "README.md").read_text()
        self.assertNotIn(f"omarchy plugin disable {plugin.STOCK_PLUGIN}", readme)


@unittest.skipUnless(shutil.which("omarchy-plugin-validate"),
                     "omarchy-plugin-validate is only on an Omarchy machine")
class OmarchysOwnValidator(unittest.TestCase):
    """The real thing, when it is available. The suites above are its stand-in."""

    def test_the_plugin_folder_passes(self):
        proc = subprocess.run(
            ["omarchy-plugin-validate", str(plugin.source_dir())],
            capture_output=True, text=True, check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr.strip())


class LauncherEntryTests(unittest.TestCase):
    """A plugin nobody can find is a plugin that does not work.

    Omarchy clones a repository into ~/.config/omarchy/plugins and stops
    there: no install hook, no manifest field for a keybinding, and nothing
    that puts a name in the launcher. Three people in a row installed this and
    reported it broken, because the only documented way to open the overlay
    was a keybind they had to write themselves. The service installs a desktop
    entry instead, the way bobbynicholas.omaland does.
    """

    def setUp(self):
        self.source = plugin.source_dir()
        self.desktop = (self.source / "displaywright.desktop").read_text()
        self.shortcuts = (self.source / "displaywright-shortcuts.desktop").read_text()
        self.installer = (self.source / "LauncherEntry.qml").read_text()

    def test_the_plugin_ships_a_desktop_entry_and_an_icon(self):
        self.assertTrue((self.source / "displaywright.desktop").is_file())
        self.assertTrue((self.source / "displaywright-shortcuts.desktop").is_file())
        self.assertTrue((self.source / "icon.png").is_file(),
                        "an entry with no icon is hard to pick out of a grid")

    def test_the_entry_opens_the_overlay(self):
        manifest = json.loads((self.source / "manifest.json").read_text())
        self.assertIn(f"toggle {manifest['id']}", self.desktop)
        self.assertIn("TryExec=omarchy-shell", self.desktop,
                      "the entry should hide itself where the shell is absent")

    def test_the_entry_can_be_found_by_what_it_does(self):
        # Nobody searches for the product name they have not learnt yet. They
        # type "display", "monitor", or "wallpaper".
        for word in ("display", "monitor", "wallpaper", "resolution"):
            self.assertIn(word, self.desktop.lower(), f"not searchable by {word!r}")

    def test_the_service_installs_and_removes_the_entry(self):
        service = (self.source / "Wallpaper.qml").read_text()
        self.assertIn("LauncherEntry", service,
                      "nothing writes the entry, so nothing appears in the launcher")
        self.assertIn("Component.onDestruction", self.installer,
                      "disabling the plugin should take its launcher entry with it")

    def test_the_way_to_get_a_keybinding_sits_next_to_the_app(self):
        # A toast was tried first and never arrived: nothing that waits inside
        # a detached process survives the teardown storm omarchy-shell puts a
        # plugin through while installing, and a second execDetached from the
        # same handler does not run at all. A second launcher entry is written
        # by the one call that does work, so it is there or the app is not.
        self.assertIn("Displaywright Shortcuts", self.shortcuts)
        self.assertIn("install-shortcuts.sh", self.installer,
                      "nothing substitutes the script path into the entry")
        self.assertIn("@SCRIPT@", self.shortcuts)
        self.assertIn("floating-terminal", self.shortcuts,
                      "the user has to see which key it picked")

    def test_everything_happens_in_one_detached_call(self):
        # Two execDetached calls from one handler: the first runs, the second
        # does not. Verified across three clean installs, twice.
        self.assertEqual(self.installer.count("Quickshell.execDetached"), 2,
                         "one call to install, one to remove -- no more")
        self.assertNotIn("sleep", self.installer,
                         "a detached process that waits does not come back")

    def test_a_reload_does_not_delete_the_entry_it_just_wrote(self):
        # The shell destroys and recreates every plugin service on each
        # reload, and `omarchy plugin add` fires dozens of reloads while it
        # installs. Removing on destruction therefore deleted the entry the
        # next instance had just written -- detached and unordered, so the
        # delete usually landed last. Every fresh install ended with no entry,
        # which is exactly what three people reported.
        self.assertIn('[ -d "$dir" ] && exit 0', self.installer,
                      "destruction must not be treated as an uninstall")

    def test_it_only_ever_touches_its_own_file(self):
        # The installer writes into ~/.local/share/applications, where the
        # user's own entries live. Both scripts gate on the marker so a file
        # somebody else wrote is never overwritten or deleted.
        self.assertIn("X-Displaywright-Managed=true", self.desktop)
        self.assertIn("marker", self.installer)
        self.assertEqual(self.installer.count('grep -q "$mark"'), 2,
                         "both install and remove must gate on the marker")
        self.assertIn("X-Displaywright-Managed=true", self.shortcuts)


if __name__ == "__main__":
    unittest.main()


class ShortcutInstallerTests(unittest.TestCase):
    """Omarchy will not let a plugin register a key or a menu row.

    The manifest has no field for either, and `omarchy plugin add` runs nothing
    from inside a plugin -- it refuses a folder containing even a symlink,
    because a plugin lands in a trusted directory without being trusted itself.
    So the shortcuts are a command the user runs, and what that command is
    allowed to do to their config is the whole of what these check.
    """

    def setUp(self):
        self.script = (plugin.source_dir() / "install-shortcuts.sh").read_text()

    def test_it_is_executable(self):
        path = plugin.source_dir() / "install-shortcuts.sh"
        self.assertTrue(path.stat().st_mode & 0o111, "cloned without the bit set")

    def test_it_asks_the_compositor_which_keys_are_taken(self):
        # Bindings can come from a Lua config that generates them at runtime,
        # or from a file symlinked into a dotfiles repo. Grepping the config
        # misses both; hyprctl knows.
        self.assertIn("hyprctl binds -j", self.script)
        self.assertNotIn("grep", self.script.split("occupant()")[1].split("}")[0])

    def test_it_never_takes_a_key_from_the_user(self):
        # Omarchy's own rule is to unbind first and say what was displaced.
        # That is a rule for someone at the keyboard; an install script has no
        # standing to make that call, and a silently stolen SUPER + F is
        # untraceable three months later.
        self.assertNotIn("unbind", self.script.lower())
        self.assertIn("not this", self.script, "no message for the all-taken case")

    def test_it_survives_a_config_that_is_a_symlink(self):
        # Editing in place through a link replaces the link with a regular
        # file and quietly detaches the dotfiles repo behind it.
        self.assertIn("readlink -f", self.script)

    def test_it_backs_up_before_editing_and_can_undo_itself(self):
        self.assertIn("cp --", self.script)
        self.assertIn("--remove", self.script)
        for mark in (">>> displaywright (managed) >>>", "<<< displaywright <<<"):
            self.assertIn(mark, self.script, "no marker, so no way to undo precisely")

    def test_it_checks_the_menu_file_still_parses(self):
        # It edits JSONC by hand. Writing a file the shell cannot read would
        # take out the user's whole menu, not just our row.
        self.assertIn("jq empty", self.script)
        self.assertIn("refusing to write", self.script)

