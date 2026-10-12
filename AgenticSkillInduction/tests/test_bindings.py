"""Offline checks using temporary synthetic evidence; no model API calls."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

EXAMPLE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("extractor_test_bindings", EXAMPLE / "bindings.py")
assert spec and spec.loader
bindings = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bindings
spec.loader.exec_module(bindings)

SKILL = """---
name: update-budget
description: Update the requested budget in a spreadsheet.
---
Open the workbook, locate the requested cell, enter the amount, and save.
Verify the displayed value after reopening the workbook.
"""


class BindingsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "input"
        self.source.mkdir()
        self.output = self.root / "output"
        (self.source / "task.json").write_text('{"instruction":"Update the requested budget."}')
        bindings.configure_roots(self.source, self.output)

    def prepare_skill(self):
        self.assertNotIn("error", bindings.read_file("task.json"))
        self.assertNotIn("error", bindings.write_file("output/update-budget/SKILL.md", SKILL))

    def test_paths_cannot_escape_roots_including_symlinks(self):
        secret = self.root / "outside.txt"
        secret.write_text("synthetic private value")
        (self.source / "link.txt").symlink_to(secret)
        for name in ["../outside.txt", str(secret), "link.txt"]:
            result = bindings.read_file(name)
            self.assertIn("error", result)
            self.assertNotIn("synthetic private value", result["content"])
        self.assertIn("error", bindings.write_file("../outside.txt", "changed"))
        self.assertEqual(secret.read_text(), "synthetic private value")

    def test_runtime_owned_outputs_are_protected(self):
        for name in bindings.RUNTIME_OWNED_OUTPUTS:
            self.assertIn("error", bindings.write_file("output/" + name, "changed"))
        self.assertFalse(list(self.output.iterdir()))

    def test_finalization_requires_task_and_post_write_readback(self):
        result = bindings.finalize_extraction()
        self.assertEqual(result["status"], "error")
        self.assertFalse(bindings.extraction_is_finalized())
        self.prepare_skill()
        self.assertIn("error", bindings.finalize_extraction())
        bindings.read_file("output/update-budget/SKILL.md")
        self.assertNotIn("error", bindings.finalize_extraction())
        manifest = json.loads((self.output / "extraction-manifest.json").read_text())
        self.assertEqual(manifest["generated_skills"][0]["sha256"], hashlib.sha256(SKILL.encode()).hexdigest())
        self.assertTrue(bindings.extraction_is_finalized())

    def test_revising_skill_requires_another_readback(self):
        self.prepare_skill()
        bindings.read_file("output/update-budget/SKILL.md")
        bindings.write_file("output/update-budget/SKILL.md", SKILL + "Check the target sheet.\n")
        self.assertIn("error", bindings.finalize_extraction())
        self.assertFalse((self.output / "extraction-manifest.json").exists())
        bindings.read_file("output/update-budget/SKILL.md")
        self.assertNotIn("error", bindings.finalize_extraction())

    def test_invalid_skill_cannot_finalize(self):
        self.prepare_skill()
        bindings.write_file("output/update-budget/SKILL.md", "No frontmatter")
        bindings.read_file("output/update-budget/SKILL.md")
        self.assertIn("error", bindings.finalize_extraction())
        self.assertFalse(bindings.extraction_is_finalized())

    @unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "ffmpeg and ffprobe required")
    def test_real_video_sampling_and_metadata_order(self):
        video = self.source / "video.mp4"
        subprocess.run([
            "ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=blue:s=160x120:d=1",
            "-c:v", "mpeg4", str(video),
        ], check=True)
        self.prepare_skill()
        bindings.read_file("output/update-budget/SKILL.md")
        sampled = bindings.watch_video("video.mp4", start_ms=100, end_ms=300, interval_ms=100)
        self.assertNotIn("error", sampled)
        self.assertEqual(len(sampled["content"]), 3)
        self.assertIn("get_video_metadata", bindings.finalize_extraction()["content"])
        # A fresh run obeys metadata ordering and exercises the exact-frame path too.
        bindings.configure_roots(self.source, self.output)
        self.prepare_skill()
        bindings.read_file("output/update-budget/SKILL.md")
        self.assertNotIn("error", bindings.get_video_metadata("video.mp4"))
        self.assertNotIn("error", bindings.extract_video_frames("video.mp4", [100, 300]))
        self.assertNotIn("error", bindings.finalize_extraction())


if __name__ == "__main__":
    unittest.main()
