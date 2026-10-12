"""Verify deterministic macOS Capture HUD snapshot artifacts."""

from __future__ import annotations

import argparse
import struct
from dataclasses import dataclass
from pathlib import Path

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
EXPECTED_STATES = (
    "armed",
    "dragging",
    "confirming",
    "saving",
    "saved",
    "permission-needed",
    "sync-pending",
)

EXPECTED_APPEARANCES = ("light",)


@dataclass(frozen=True, slots=True)
class ExpectedSnapshotSize:
    """One snapshot viewport expected from the Swift renderer.

    Attributes:
        directory: Directory name that stores snapshots for this viewport.
        width: Expected PNG pixel width.
        height: Expected PNG pixel height.
    """

    directory: str
    width: int
    height: int


EXPECTED_SIZES = (
    ExpectedSnapshotSize(directory="1440x900", width=1440, height=900),
    ExpectedSnapshotSize(directory="1024x768", width=1024, height=768),
    ExpectedSnapshotSize(directory="390x844", width=390, height=844),
)


def main() -> int:
    """Run snapshot verification from the command line.

    Returns:
        Process exit status.
    """

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True, help="Root directory containing HUD snapshots.")
    args = parser.parse_args()
    errors = list(_verify(args.root))
    if errors:
        for error in errors:
            print(error)
        return 1
    print(
        "Verified "
        f"{len(EXPECTED_APPEARANCES) * len(EXPECTED_SIZES) * len(EXPECTED_STATES)} "
        f"light Capture HUD snapshots in {args.root}"
    )
    return 0


def _verify(root: Path) -> tuple[str, ...]:
    errors: list[str] = []
    stale_dark = root / "dark"
    if stale_dark.exists():
        errors.append(f"stale dark-mode snapshot directory should be removed: {stale_dark}")
    for appearance in EXPECTED_APPEARANCES:
        for expected_size in EXPECTED_SIZES:
            for state in EXPECTED_STATES:
                file = root / appearance / expected_size.directory / f"{state}.png"
                if not file.exists():
                    errors.append(f"missing snapshot: {file}")
                    continue
                if file.stat().st_size < 8_000:
                    errors.append(f"snapshot is unexpectedly small: {file}")
                    continue
                try:
                    width, height = _read_png_dimensions(file)
                except ValueError as exc:
                    errors.append(f"{file}: {exc}")
                    continue
                if width != expected_size.width or height != expected_size.height:
                    errors.append(
                        f"{file}: expected {expected_size.width}x{expected_size.height}, got {width}x{height}"
                    )
        reference = root / appearance / "design-reference.png"
        if not reference.exists():
            errors.append(f"missing design reference snapshot: {reference}")
        elif reference.stat().st_size < 8_000:
            errors.append(f"design reference snapshot is unexpectedly small: {reference}")
        else:
            try:
                width, height = _read_png_dimensions(reference)
            except ValueError as exc:
                errors.append(f"{reference}: {exc}")
            else:
                if width != 1440 or height != 900:
                    errors.append(f"{reference}: expected 1440x900, got {width}x{height}")
    return tuple(errors)


def _read_png_dimensions(file: Path) -> tuple[int, int]:
    with file.open("rb") as png_file:
        signature = png_file.read(8)
        if signature != PNG_SIGNATURE:
            raise ValueError("not a PNG file")
        length = png_file.read(4)
        chunk_type = png_file.read(4)
        if len(length) != 4 or chunk_type != b"IHDR":
            raise ValueError("missing PNG IHDR chunk")
        width_bytes = png_file.read(4)
        height_bytes = png_file.read(4)
        if len(width_bytes) != 4 or len(height_bytes) != 4:
            raise ValueError("truncated PNG IHDR dimensions")
    return struct.unpack(">I", width_bytes)[0], struct.unpack(">I", height_bytes)[0]


if __name__ == "__main__":
    raise SystemExit(main())
