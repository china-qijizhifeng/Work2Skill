"""Verify recording UI snapshot artifacts for release evidence."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image

EXPECTED_RECORDING_UI_FILES = (
    "01-trigger-menu-recording-active.png",
    "02-region-preparation-chrome-docs.png",
    "03-region-preparation-figma-prototype.png",
    "04-countdown-three.png",
    "05-countdown-recording.png",
    "06-hud-recording.png",
    "07-hud-paused.png",
    "08-hud-input-trace-degraded.png",
    "09-hud-user-marked.png",
    "10-hud-finalizing.png",
    "11-boundary-recording.png",
    "12-boundary-paused.png",
    "13-completion-ready-to-save.png",
    "14-completion-input-trace-degraded.png",
    "15-completion-scope-needs-review.png",
    "16-completion-multi-segment.png",
    "17-completion-saving.png",
    "18-completion-save-failure.png",
    "19-completion-missing-preview-frame.png",
    "20-discard-confirmation.png",
    "21-region-preparation-accessibility-degraded.png",
    "22-recording-permission-screen-recording-denied.png",
)


@dataclass(frozen=True, slots=True)
class RecordingUISnapshotFacts:
    """Measured facts for one recording UI snapshot.

    Attributes:
        file: Snapshot file name.
        width: Image width in pixels.
        height: Image height in pixels.
        unique_sample_count: Coarse visual diversity count.
        alpha_min: Minimum sampled alpha value.
        alpha_max: Maximum sampled alpha value.
    """

    file: str
    width: int
    height: int
    unique_sample_count: int
    alpha_min: int
    alpha_max: int


def verify(root: Path) -> list[RecordingUISnapshotFacts]:
    """Verify recording UI screenshots and return measured facts.

    Args:
        root: Directory containing recording UI PNGs.

    Returns:
        Measured facts for all expected snapshots.

    Raises:
        SystemExit: If snapshots are missing, duplicated, blank, or collapsed.
    """

    errors: list[str] = []
    facts: list[RecordingUISnapshotFacts] = []
    expected = set(EXPECTED_RECORDING_UI_FILES)
    if not root.exists():
        raise SystemExit(f"recording UI snapshot root is missing: {root}")
    extras = sorted(path.name for path in root.glob("*.png") if path.name not in expected)
    duplicate_exports = [name for name in extras if " 2." in name or " copy." in name]
    if duplicate_exports:
        errors.append(f"stale duplicate recording UI snapshots found: {', '.join(duplicate_exports)}")
    for name in EXPECTED_RECORDING_UI_FILES:
        path = root / name
        if not path.exists():
            errors.append(f"missing recording UI snapshot: {path}")
            continue
        item = _facts(path)
        facts.append(item)
        minimum_unique = 2 if "boundary" in name else 6
        if item.width < 42 or item.height < 40:
            errors.append(f"{name} is too small for visual review: {item.width}x{item.height}")
        if item.unique_sample_count < minimum_unique:
            errors.append(f"{name} looks blank or visually collapsed")
        if item.alpha_max == 0:
            errors.append(f"{name} is fully transparent")
    if errors:
        raise SystemExit("\n".join(errors))
    return facts


def _facts(path: Path) -> RecordingUISnapshotFacts:
    image = Image.open(path).convert("RGBA")
    colors: set[tuple[int, int, int, int]] = set()
    alphas: list[int] = []
    step_x = max(1, image.width // 120)
    step_y = max(1, image.height // 120)
    for y in range(0, image.height, step_y):
        for x in range(0, image.width, step_x):
            pixel = image.getpixel((x, y))
            colors.add(pixel)
            alphas.append(pixel[3])
    return RecordingUISnapshotFacts(
        file=path.name,
        width=image.width,
        height=image.height,
        unique_sample_count=len(colors),
        alpha_min=min(alphas) if alphas else 0,
        alpha_max=max(alphas) if alphas else 0,
    )


def main() -> None:
    """Run the recording UI snapshot verifier from the command line."""

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(".qa/recording-ui"))
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    facts = verify(args.root)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps([asdict(item) for item in facts], indent=2), encoding="utf-8")
    print(f"Verified {len(facts)} recording UI snapshots in {args.root}")


if __name__ == "__main__":
    main()
