"""Publication-hygiene regressions using disposable files and Git indexes.

Run: python tests/verification/test_repo_hygiene.py
No repository files, network services, builds or hardware are modified.
"""
from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("repo_hygiene_under_test", ROOT / "scripts/repo_hygiene.py")
assert SPEC and SPEC.loader
hygiene = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hygiene)


class PublicationHygiene(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="trecap-hygiene-")
        self.addCleanup(self.temp.cleanup)
        # Match the CLI root contract: Windows TEMP may use a short-name
        # alias or junction while Markdown destinations use resolve().
        self.root = Path(self.temp.name).resolve()

    def write(self, relative, content):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def audit(self):
        # Most fixtures exercise the source-only path, independent of the machine's
        # current directory and any enclosing Git checkout.
        with patch.object(hygiene, "git_source_files", return_value=None):
            return hygiene.check(self.root)[1]

    @unittest.skipUnless(shutil.which("git"), "Git is required for index-scope regression")
    def test_nested_git_scope_keeps_tracked_ignored_files_visible(self):
        env = os.environ.copy()
        # A fixture must not use an unrelated worktree/index or local Git hooks.
        for name in list(env):
            if name.startswith("GIT_"):
                env.pop(name)
        env["GIT_CONFIG_GLOBAL"] = os.devnull
        env["GIT_CONFIG_NOSYSTEM"] = "1"
        def git(*args):
            subprocess.run(["git", "-C", str(self.root), *args], env=env,
                           check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        with patch.dict(os.environ, env, clear=True):
            git("init", "--quiet")
            self.write("phase2/.gitignore", "*.zip\n")
            self.write("phase2/source.py", "answer = 42\n")
            self.write("phase2/untracked-export.zip", "local export")
            self.write("phase2/tracked-export.zip", "accidental tracked export")
            self.write("outside.py", "this_is_outside_phase2 = True\n")
            git("add", "-f", "phase2/tracked-export.zip")
            files = hygiene.git_source_files(self.root / "phase2")
            self.assertIsNotNone(files)
            self.assertEqual({p.name for p in files},
                             {".gitignore", "source.py", "tracked-export.zip"})
            _, issues = hygiene.check(self.root / "phase2")
        self.assertEqual(len(issues), 1, issues)
        self.assertIn("tracked-export.zip", issues[0])
        self.assertIn("local build/output", issues[0])

    def test_public_receipt_is_still_scanned_for_credentials(self):
        token = "gh" + "p_" + "A" * 36
        self.write("docs/results/hps_cpu_benchmark_20260925/data/qualification/fixture.log",
                   "qualification passed\n" + token + "\n")
        issues = self.audit()
        self.assertEqual(len(issues), 1, issues)
        self.assertIn("possible credential", issues[0])
        self.assertNotIn(token, issues[0])

    def test_other_logs_are_not_allowed_as_public_receipts(self):
        self.write("docs/results/other/fixture.log", "raw capture\n")
        self.assertTrue(any("local build/output" in issue for issue in self.audit()))

    def test_template_links_use_output_directory_and_missing_targets_fail(self):
        self.write("experiments/ifft_zero_isolation/study/report_template.md",
                   "[trial data](data/trials.csv)\n")
        target = self.write("docs/results/ifft_zero_isolation_20260925/data/trials.csv",
                            "trial,value\n1,2\n")
        self.assertEqual(self.audit(), [])
        target.unlink()
        issues = self.audit()
        self.assertEqual(len(issues), 1, issues)
        self.assertIn("relative Markdown target does not exist", issues[0])

    def make_presentation(self, title="Capstone", relationship=None, extra=None):
        path = self.root / "fixture.pptx"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("[Content_Types].xml", "<Types/>")
            archive.writestr("ppt/presentation.xml", "<presentation/>")
            archive.writestr("docProps/core.xml", "<properties><title>" + title + "</title></properties>")
            if relationship is not None:
                archive.writestr("ppt/_rels/presentation.xml.rels", relationship)
            if extra is not None:
                archive.writestr(extra, b"opaque payload")
        return path

    def test_presentation_xml_is_validated(self):
        self.make_presentation()
        self.assertEqual(self.audit(), [])
        self.make_presentation(title="<malformed")
        self.assertTrue(any("invalid or unreadable" in issue for issue in self.audit()))

    def test_presentation_metadata_credentials_are_detected_without_values(self):
        token = "gh" + "p_" + "B" * 36
        self.make_presentation(title=token)
        issues = self.audit()
        self.assertTrue(any("possible credential" in issue for issue in issues))
        self.assertTrue(all(token not in issue for issue in issues))

    def test_presentation_personal_paths_are_detected(self):
        personal_path = "C:" + "/Users/" + "sample-person/private.txt"
        self.make_presentation(title=personal_path)
        issues = self.audit()
        self.assertTrue(any("personal absolute path" in issue for issue in issues))
        self.assertTrue(all(personal_path not in issue for issue in issues))

    def test_presentation_local_links_and_embedded_programs_are_rejected(self):
        self.make_presentation(
            relationship='<Relationships><Relationship TargetMode="External" '
                         'Target="file:///private/report.txt"/></Relationships>',
            extra="ppt/vbaProject.bin")
        issues = self.audit()
        self.assertTrue(any("external relationship" in issue for issue in issues))
        self.assertTrue(any("unreviewed binary part" in issue for issue in issues))


if __name__ == "__main__":
    unittest.main()
