# Copyright (C) 2026 Miqdad
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# This file is part of Luna. See LICENSE and NOTICE at the repository root.

import os
import shutil
import subprocess
import unittest


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestInstallerScripts(unittest.TestCase):
    """Verify Windows and POSIX installers provide completion feedback and valid syntax."""

    def test_windows_installer_has_completion_banner_prompt_and_valid_syntax(self):
        ps1_path = os.path.join(REPO_ROOT, "install.ps1")
        with open(ps1_path, "r", encoding="utf-8") as f:
            content = f.read()

        for expected in (
            "Luna $actionWord complete!",
            "Location : $lunaDir",
            "Desktop & Start Menu",
            ".env and saved Workspace media are kept across updates.",
            "Close Luna first, then re-run the same PowerShell install command.",
            "Press Enter to launch Luna now (or type N to exit)",
            'LUNA_NO_START -ne "1"',
            "IsInputRedirected",
        ):
            self.assertIn(expected, content)

        if os.name == "nt":
            ps_exe = shutil.which("powershell") or shutil.which("pwsh")
            self.assertIsNotNone(ps_exe)
            parse_cmd = (
                f"$err = $null; "
                f"[void][System.Management.Automation.Language.Parser]::ParseFile('{ps1_path}', [ref]$null, [ref]$err); "
                f"if ($err.Count -gt 0) {{ $err | ForEach-Object {{ Write-Error $_.ToString() }}; exit 1 }}"
            )
            proc = subprocess.run([ps_exe, "-NoProfile", "-Command", parse_cmd], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)

    def test_posix_installer_has_completion_banner_and_tty_safe_prompt(self):
        sh_path = os.path.join(REPO_ROOT, "install.sh")
        with open(sh_path, "r", encoding="utf-8") as f:
            content = f.read()

        for expected in (
            "Luna %s complete!",
            "Launcher : ./start.sh",
            ".env and saved Workspace media are kept across updates.",
            "Press Enter to launch Luna now (or type n to exit):",
            'LUNA_NO_START:-}" != "1"',
            "< /dev/tty",
        ):
            self.assertIn(expected, content)

        sh_exe = shutil.which("sh")
        if sh_exe:
            proc = subprocess.run([sh_exe, "-n", sh_path], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, msg=proc.stderr or proc.stdout)


if __name__ == "__main__":
    unittest.main()
