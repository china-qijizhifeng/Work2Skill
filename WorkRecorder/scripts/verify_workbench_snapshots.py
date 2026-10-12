"""Verify Workbench snapshot visual facts.

The check is intentionally lightweight: it does not try to do a brittle
pixel-perfect diff against a designer reference. It catches the failures that
made the selected event view feel unfinished: blank panels, missing right-side
inspector content, and a cropped bottom trust area.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageStat

EXPECTED_FILES = (
    "overview-selected.png",
    "inspector-meituan-summary.png",
    "inspector-meituan-text-unloaded.png",
    "inspector-meituan-text-loaded.png",
    "inspector-meituan-raw.png",
    "inspector-meituan-diagnostics.png",
    "inspector-real-meituan-summary.png",
)
EXPECTED_RECORDING_REVIEW_FILES = (
    "recording-review-default.png",
    "recording-review-materials-panel.png",
    "recording-review-dense-long-title.png",
    "recording-review-keyframes-only.png",
    "recording-review-four-step-min-size.png",
    "recording-review-narrow.png",
    "recording-review-min-size.png",
    "recording-review-loaded-playback.png",
    "recording-review-controls-folded.png",
)
REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class SnapshotFacts:
    """Visual facts used by the Workbench snapshot gate.

    Attributes:
        file: Snapshot file name.
        width: Rendered image width in pixels.
        height: Rendered image height in pixels.
        inspector_unique_colors: Coarse color diversity in the right inspector.
        inspector_luminance: Mean inspector luminance normalized to 0..1.
        footer_delta_from_white: How far the bottom inspector area is from blank white.
    """

    file: str
    width: int
    height: int
    inspector_unique_colors: int
    inspector_luminance: float
    footer_delta_from_white: float


def _luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = [channel / 255.0 for channel in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _unique_sample_count(image: Image.Image, step: int = 12) -> int:
    rgb = image.convert("RGB")
    colors: set[tuple[int, int, int]] = set()
    for y in range(0, rgb.height, max(1, rgb.height // step)):
        for x in range(0, rgb.width, max(1, rgb.width // step)):
            colors.add(rgb.getpixel((x, y)))
    return len(colors)


def _mean_rgb(image: Image.Image) -> tuple[float, float, float]:
    stat = ImageStat.Stat(image.convert("RGB"))
    red, green, blue = stat.mean[:3]
    return red, green, blue


def _facts(path: Path) -> SnapshotFacts:
    image = Image.open(path).convert("RGB")
    width, height = image.size
    inspector = image.crop((int(width * 0.68), int(height * 0.10), int(width * 0.985), int(height * 0.94)))
    footer = image.crop((int(width * 0.70), int(height * 0.74), int(width * 0.985), int(height * 0.94)))
    inspector_rgb = _mean_rgb(inspector)
    footer_rgb = _mean_rgb(footer)
    footer_delta = sum(abs(channel - 255.0) for channel in footer_rgb) / 3.0
    return SnapshotFacts(
        file=path.name,
        width=width,
        height=height,
        inspector_unique_colors=_unique_sample_count(inspector),
        inspector_luminance=_luminance(inspector_rgb),
        footer_delta_from_white=footer_delta,
    )


def _real_fixture_path(root: Path) -> Path | None:
    candidates = [
        REPO_ROOT / "tests" / "fixtures" / "workbench" / "synthetic-inspect.json",
    ]
    return next((path for path in candidates if path.exists()), None)


def verify(root: Path) -> list[SnapshotFacts]:
    """Verify required Workbench screenshots and return their measured facts.

    Args:
        root: Directory containing Workbench snapshot PNGs.

    Returns:
        Measured facts for each required snapshot.

    Raises:
        SystemExit: If a required screenshot is missing, blank, cropped, or if
            the synthetic fixture no longer covers long text and hidden artifacts.
    """

    errors: list[str] = []
    facts: list[SnapshotFacts] = []
    for name in EXPECTED_FILES:
        path = root / name
        if not path.exists():
            errors.append(f"missing Workbench snapshot: {path}")
            continue
        item = _facts(path)
        facts.append(item)
        if item.width < 1500 or item.height < 900:
            errors.append(f"{name} is too small for visual review: {item.width}x{item.height}")
        if item.inspector_unique_colors < 8:
            errors.append(f"{name} inspector region is visually too flat")
        if not 0.72 <= item.inspector_luminance <= 0.985:
            errors.append(f"{name} inspector luminance is out of range: {item.inspector_luminance:.3f}")
    for name in EXPECTED_RECORDING_REVIEW_FILES:
        path = root / name
        if not path.exists():
            errors.append(f"missing recording review snapshot: {path}")
            continue
        item = _facts(path)
        facts.append(item)
        if item.width < 1_000 or item.height < 700:
            errors.append(f"{name} is too small for large review QA: {item.width}x{item.height}")
        if item.inspector_unique_colors < 7:
            errors.append(f"{name} right review panel is visually too flat")
        if item.footer_delta_from_white < 1.5:
            errors.append(f"{name} bottom timeline/summary area looks blank or cropped")
        if not 0.20 <= item.inspector_luminance <= 0.985:
            errors.append(f"{name} review panel luminance is out of range: {item.inspector_luminance:.3f}")
    selected = next((item for item in facts if item.file == "overview-selected.png"), None)
    if selected and selected.footer_delta_from_white < 2.0:
        errors.append("overview-selected bottom-right trust/footer area looks blank or cropped")
    overview = next((item for item in facts if item.file == "overview.png"), None)
    if overview and selected:
        if selected.height < overview.height * 0.92:
            errors.append("selected Workbench review viewport is too short compared with overview")
    real_fixture = _real_fixture_path(root)
    if real_fixture is not None:
        payload = json.loads(real_fixture.read_text(encoding="utf-8"))
        data = payload.get("data", {})
        source = data.get("source", {})
        if source.get("origin") != "https://example.test":
            errors.append("synthetic inspect fixture origin drifted; expected example.test")
        if len(data.get("clean_page_text", "")) < 1000:
            errors.append("synthetic inspect fixture clean_page_text is too short for long-text visual QA")
        if len(data.get("hidden_artifacts", [])) < 3:
            errors.append("synthetic inspect fixture no longer covers hidden artifact display")
    if errors:
        raise SystemExit("\n".join(errors))
    return facts


def main() -> None:
    """Run the Workbench snapshot verifier from the command line.

    Raises:
        SystemExit: Propagates visual gate failures from ``verify``.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(".qa/workbench"))
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    facts = verify(args.root)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps([asdict(item) for item in facts], indent=2), encoding="utf-8")
    print(f"Verified {len(facts)} Workbench snapshots in {args.root}")


if __name__ == "__main__":
    main()
