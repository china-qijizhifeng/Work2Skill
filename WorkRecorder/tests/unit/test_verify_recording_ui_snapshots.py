from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from scripts.verify_recording_ui_snapshots import EXPECTED_RECORDING_UI_FILES, verify


def test_verify_recording_ui_snapshots_accepts_complete_set(tmp_path: Path) -> None:
    for index, name in enumerate(EXPECTED_RECORDING_UI_FILES):
        _write_png(tmp_path / name, index=index)

    facts = verify(tmp_path)

    assert len(facts) == len(EXPECTED_RECORDING_UI_FILES)
    assert {fact.file for fact in facts} == set(EXPECTED_RECORDING_UI_FILES)


def test_verify_recording_ui_snapshots_rejects_duplicate_exports(tmp_path: Path) -> None:
    for index, name in enumerate(EXPECTED_RECORDING_UI_FILES):
        _write_png(tmp_path / name, index=index)
    _write_png(tmp_path / "01-trigger-menu-recording-active 2.png", index=30)

    with pytest.raises(SystemExit, match="stale duplicate"):
        verify(tmp_path)


def test_verify_recording_ui_snapshots_rejects_missing_snapshot(tmp_path: Path) -> None:
    for index, name in enumerate(EXPECTED_RECORDING_UI_FILES[1:]):
        _write_png(tmp_path / name, index=index)

    with pytest.raises(SystemExit, match="missing recording UI snapshot"):
        verify(tmp_path)


def _write_png(path: Path, *, index: int) -> None:
    image = Image.new("RGBA", (96, 64), (230, 250, 252, 255))
    for x in range(10, 86):
        for y in range(10, 54):
            image.putpixel((x, y), ((20 + index * 13 + x) % 255, (90 + y) % 255, (110 + x + y) % 255, 255))
    image.save(path)
