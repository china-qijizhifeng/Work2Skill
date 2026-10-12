"""Create visual review artifacts for a Workbench design round.

This script intentionally compares screenshots in a human-readable way rather
than pretending to be a pixel-perfect approval system. Each design round gets a
side-by-side image, a soft diff, facts, and a review stub so the iteration count
stays honest.
"""

from __future__ import annotations

import argparse
import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageStat

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class RoundImageFacts:
    """Stable visual metrics for one exported Workbench review image.

    Attributes:
        file: Review image file name.
        width: Rendered image width in pixels.
        height: Rendered image height in pixels.
        average_luminance: Mean luminance normalized to 0..1.
        teal_ratio: Approximate ratio of Tiffany/teal pixels.
        non_white_ratio: Approximate ratio of non-white pixels.
    """

    file: str
    width: int
    height: int
    average_luminance: float
    teal_ratio: float
    non_white_ratio: float


def _luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = [channel / 255.0 for channel in rgb]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _facts(path: Path) -> RoundImageFacts:
    image = Image.open(path).convert("RGB")
    small = image.resize((240, max(1, int(240 * image.height / image.width)))).convert("RGB")
    raw = small.tobytes()
    teal = 0
    non_white = 0
    total = 0
    for index in range(0, len(raw), 3):
        r, g, b = raw[index], raw[index + 1], raw[index + 2]
        total += 1
        if g > r + 10 and b > r + 4 and g > 135:
            teal += 1
        if min(255 - r, 255 - g, 255 - b) < -6 or (r + g + b) / 3 < 246:
            non_white += 1
    raw_mean = ImageStat.Stat(image).mean
    mean = (raw_mean[0], raw_mean[1], raw_mean[2])
    return RoundImageFacts(
        file=path.name,
        width=image.width,
        height=image.height,
        average_luminance=round(_luminance(mean), 4),
        teal_ratio=round(teal / max(1, total), 4),
        non_white_ratio=round(non_white / max(1, total), 4),
    )


def _fit_to_reference(image: Image.Image, reference: Image.Image) -> Image.Image:
    fitted = image.convert("RGB").copy()
    fitted.thumbnail(reference.size, Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", reference.size, (248, 251, 251))
    canvas.paste(fitted, ((reference.width - fitted.width) // 2, (reference.height - fitted.height) // 2))
    return canvas


def _write_comparison(current: Path, reference: Path, output: Path) -> None:
    reference_image = Image.open(reference).convert("RGB")
    current_image = _fit_to_reference(Image.open(current), reference_image)
    gutter = 24
    side_by_side = Image.new(
        "RGB",
        (reference_image.width * 2 + gutter, reference_image.height),
        (246, 250, 250),
    )
    side_by_side.paste(reference_image, (0, 0))
    side_by_side.paste(current_image, (reference_image.width + gutter, 0))
    side_by_side.save(output / f"{current.stem}-side-by-side.png")

    diff = ImageChops.difference(reference_image, current_image)
    diff = ImageEnhance.Contrast(diff).enhance(3.2)
    diff = ImageEnhance.Brightness(diff).enhance(2.0)
    diff.save(output / f"{current.stem}-diff.png")


def _real_fixture_path(root: Path) -> Path | None:
    candidates = [
        REPO_ROOT / "tests" / "fixtures" / "workbench" / "synthetic-inspect.json",
    ]
    return next((path for path in candidates if path.exists()), None)


def main() -> None:
    """Build a per-round visual review folder from current Workbench screenshots.

    Raises:
        SystemExit: If the current Workbench screenshots are missing.
    """

    parser = argparse.ArgumentParser()
    parser.add_argument("--round", required=True, help="Round label, e.g. 07")
    parser.add_argument("--root", type=Path, default=Path(".qa/workbench"))
    parser.add_argument("--output-root", type=Path, default=Path(".qa/workbench-rounds"))
    parser.add_argument("--notes", default="")
    args = parser.parse_args()

    round_dir = args.output_root / f"round-{args.round}"
    round_dir.mkdir(parents=True, exist_ok=True)

    current_files = ["overview.png", "overview-selected.png"]
    reference_for = {
        "overview.png": "非展开.png",
        "overview-selected.png": "展开.png",
    }
    facts: list[RoundImageFacts] = []
    for name in current_files:
        source = args.root / name
        if not source.exists():
            raise SystemExit(f"missing Workbench snapshot: {source}")
        destination = round_dir / name
        shutil.copy2(source, destination)
        facts.append(_facts(destination))
        reference = args.root / reference_for[name]
        if reference.exists():
            _write_comparison(destination, reference, round_dir)

    real_fixture = _real_fixture_path(args.root)
    real_snapshot = args.root / "inspector-real-meituan-summary.png"
    real_check: dict[str, object] = {
        "fixture_present": real_fixture is not None,
        "snapshot_present": real_snapshot.exists(),
    }
    if real_fixture is not None:
        payload = json.loads(real_fixture.read_text(encoding="utf-8"))
        data = payload.get("data", {})
        real_check.update(
            {
                "event_id": data.get("event_id"),
                "title": data.get("source", {}).get("title"),
                "origin": data.get("source", {}).get("origin"),
                "clean_page_text_chars": len(data.get("clean_page_text", "")),
                "canonical_text_chars": len(data.get("canonical_text", "")),
                "hidden_artifact_count": len(data.get("hidden_artifacts", [])),
                "raw_artifact_count": len(data.get("raw_artifacts", [])),
            }
        )
    if real_snapshot.exists():
        shutil.copy2(real_snapshot, round_dir / "inspector-real-meituan-summary.png")
    (round_dir / "real-data-check.json").write_text(
        json.dumps(real_check, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    (round_dir / "facts.json").write_text(
        json.dumps([asdict(item) for item in facts], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    review = [
        f"# Workbench Round {args.round} Review",
        "",
        "## 本轮改动",
        "",
        args.notes or "- 待补充。",
        "",
        "## 对照结论",
        "",
        "- 已生成 `overview-side-by-side.png` / `overview-diff.png`。",
        "- 已生成 `overview-selected-side-by-side.png` / `overview-selected-diff.png`。",
        "- 该目录记录的是一次真实设计状态，不把重复渲染稳定性测试计入设计轮次。",
    ]
    (round_dir / "review.md").write_text("\n".join(review) + "\n", encoding="utf-8")
    print(f"Wrote Workbench round artifacts to {round_dir}")


if __name__ == "__main__":
    main()
