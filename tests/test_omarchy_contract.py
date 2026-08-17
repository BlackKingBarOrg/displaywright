"""The Omarchy behaviour this feature leans on, pinned down.

hyprlayout only writes the toggle file; Omarchy is what puts the panel back when
the external display goes away. These tests drive Omarchy's own scripts against a
fake HOME with stub commands on PATH, so they assert the contract without
touching real hardware. If a future Omarchy changes the mechanism, they fail here
rather than leaving someone with a black laptop.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from hyprlayout import omarchy

CLAMSHELL = "/usr/share/omarchy/bin/omarchy-hyprland-monitor-clamshell"
RECOVER = "/usr/share/omarchy/bin/omarchy-hw-recover-internal-monitor"

MONITORS_LUA = 'hl.monitor({ output = "eDP-1", mode = "3200x2000@120", position = "0x56", scale = 2 })\n'

STUBS = {
    "omarchy-hyprland-monitor-laptop": "#!/usr/bin/env bash\necho eDP-1\n",
    "omarchy-hyprland-monitor-internal": "#!/usr/bin/env bash\nexit 0\n",
    "omarchy-hyprland-monitor-internal-mirror": "#!/usr/bin/env bash\nexit 0\n",
    "omarchy-hw-clamshell": "#!/usr/bin/env bash\nexit 1\n",  # lid open
}


@unittest.skipUnless(
    Path(CLAMSHELL).exists() and Path(RECOVER).exists() and shutil.which("jq"),
    "needs Omarchy's monitor scripts installed",
)
class OmarchyContractTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name)
        self.home = self.root / "home"
        self.stubs = self.root / "stubs"
        self.log = self.root / "hyprctl.log"

        self.toggle = (
            self.home / ".local/state/omarchy/toggles/hypr" / omarchy.TOGGLE_NAME
        )
        self.toggle.parent.mkdir(parents=True)
        (self.home / ".config/hypr").mkdir(parents=True)
        (self.home / ".config/hypr/monitors.lua").write_text(MONITORS_LUA)
        self.stubs.mkdir()

        for name, body in STUBS.items():
            self._stub(name, body)
        self._stub(
            "hyprctl",
            "#!/usr/bin/env bash\n"
            f'printf "%s\\n" "$*" >>"{self.log}"\n'
            'if [[ "$*" == *"monitors all -j"* ]]; then\n'
            '  echo \'[{"name":"eDP-1","disabled":true,"scale":2,"x":0,"y":56}]\'\n'
            "fi\nexit 0\n",
        )

    def _stub(self, name, body):
        path = self.stubs / name
        path.write_text(body)
        path.chmod(0o755)

    def _env(self, **extra):
        env = dict(os.environ)
        env["HOME"] = str(self.home)
        env["PATH"] = f"{self.stubs}:{env['PATH']}"
        env.update(extra)
        return env

    def _set_external_active(self, active):
        self._stub(
            "omarchy-hyprland-monitor-external-active",
            f"#!/usr/bin/env bash\nexit {0 if active else 1}\n",
        )

    def _write_toggle(self):
        self.toggle.write_text(omarchy.render_toggle("eDP-1"))

    def _hyprctl_calls(self):
        if not self.log.exists():
            return []
        return [line for line in self.log.read_text().splitlines() if "monitors all" not in line]

    # ------------------------------------------------------------- runtime half

    def test_panel_comes_back_when_no_external_is_active(self):
        self._write_toggle()
        self._set_external_active(False)
        subprocess.run([CLAMSHELL], env=self._env(), check=False, timeout=30)
        calls = " ".join(self._hyprctl_calls())
        self.assertIn('output = "eDP-1"', calls)
        self.assertNotIn("disabled = true", calls)
        # Position and scale come from the rule hyprlayout leaves in monitors.lua,
        # which is exactly why a switched-off panel is still written as enabled.
        self.assertIn('position = "0x56"', calls)
        self.assertIn("scale = 2", calls)

    def test_panel_stays_off_while_an_external_is_active(self):
        self._write_toggle()
        self._set_external_active(True)
        subprocess.run([CLAMSHELL], env=self._env(), check=False, timeout=30)
        self.assertEqual(
            [c for c in self._hyprctl_calls() if "eval" in c],
            [],
            "the panel was switched on while docked",
        )

    # ---------------------------------------------------------------- boot half

    def _drm(self, external_connected):
        drm = self.root / "drm"
        for name, status in (
            ("card0-eDP-1", "connected"),
            ("card0-DP-1", "connected" if external_connected else "disconnected"),
        ):
            (drm / name).mkdir(parents=True, exist_ok=True)
            (drm / name / "status").write_text(status + "\n")
        return drm

    def test_toggle_is_cleared_before_a_session_with_nothing_plugged_in(self):
        self._write_toggle()
        drm = self._drm(external_connected=False)
        subprocess.run(
            [RECOVER], env=self._env(OMARCHY_DRM_PATH=str(drm)), check=False, timeout=30
        )
        self.assertFalse(self.toggle.exists(), "would have booted to a black laptop")

    def test_toggle_survives_a_session_that_is_still_docked(self):
        self._write_toggle()
        drm = self._drm(external_connected=True)
        subprocess.run(
            [RECOVER], env=self._env(OMARCHY_DRM_PATH=str(drm)), check=False, timeout=30
        )
        self.assertTrue(self.toggle.exists())

    def test_our_toggle_content_is_what_omarchy_expects_to_load(self):
        # The file is require()d as Lua by Omarchy's toggle loader.
        text = omarchy.render_toggle("eDP-1")
        self.assertIn("hl.monitor(", text)
        self.assertTrue(all(line.startswith("--") or "hl.monitor" in line
                            for line in text.splitlines() if line.strip()))


if __name__ == "__main__":
    unittest.main()
