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

    def test_the_readme_says_how_to_open_the_arrangement(self):
        # The overlay has no bar icon and no menu entry: being summoned is the
        # only way in, so the command has to be written down.
        readme = " ".join((self.source / "README.md").read_text().split())
        self.assertIn("summon ai.bkblab.displaywright", readme)
        self.assertIn("bindings.lua", readme)

    def test_the_readme_points_at_the_window(self):
        # Editing JSON is the floor, not the intended experience. Someone who
        # would rather click has to be able to find out that a window exists.
        # Matched against unwrapped text: the README is hard-wrapped at 80 and a
        # phrase lands across a line break as often as not.
        readme = " ".join((self.source / "README.md").read_text().split())
        self.assertIn("separate project", readme)
        self.assertIn("github.com/BlackKingBarOrg/displaywright", readme)

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


if __name__ == "__main__":
    unittest.main()
