"""Generate the subtle rainbow refraction asset used by the Workbench sidebar."""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any, cast

from PIL import Image, ImageChops, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "apps/macos_capture/Sources/WorkRecorderCapture/Resources/Workbench/sidebar_prism_caustic.png"


def _clamp(value: float, lower: float = 0.0, upper: float = 1.0) -> float:
    return max(lower, min(upper, value))


def _smoothstep(edge0: float, edge1: float, value: float) -> float:
    t = _clamp((value - edge0) / max(edge1 - edge0, 1e-6))
    return t * t * (3.0 - 2.0 * t)


def _add_color(
    rgba: tuple[float, float, float, float],
    color: tuple[float, float, float],
    alpha: float,
) -> tuple[float, float, float, float]:
    alpha = _clamp(alpha)
    red, green, blue, opacity = rgba
    return (
        red + color[0] * alpha,
        green + color[1] * alpha,
        blue + color[2] * alpha,
        opacity + alpha,
    )


def _generate_caustic(width: int = 760, height: int = 2020, seed: int = 42) -> Image.Image:
    rng = random.Random(seed)
    arc_specs = [
        (-0.034, (0.56, 0.96, 1.00), 0.110),
        (-0.018, (0.44, 0.83, 1.00), 0.082),
        (-0.002, (0.73, 0.66, 1.00), 0.062),
        (0.014, (1.00, 0.67, 0.88), 0.052),
        (0.030, (1.00, 0.91, 0.52), 0.035),
    ]
    beam_specs = [
        (0.86, -0.54, 0.930, 0.018, (0.54, 0.96, 1.00), 0.060),
        (0.78, -0.47, 0.885, 0.014, (0.83, 0.72, 1.00), 0.045),
        (0.70, -0.39, 0.842, 0.012, (1.00, 0.72, 0.91), 0.035),
        (0.60, -0.33, 0.802, 0.009, (1.00, 0.94, 0.60), 0.020),
    ]
    cx, cy = 0.02, 1.045
    rx, ry = 0.58, 0.26
    pixels: list[tuple[int, int, int, int]] = []

    for py in range(height):
        y = py / height
        for px in range(width):
            x = px / width
            rgba = (0.0, 0.0, 0.0, 0.0)

            # The main glow is intentionally anchored below the visible sidebar,
            # like light refracting through a glass edge rather than a blob.
            radial = math.sqrt(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2)
            halo = max(0.0, 1.0 - radial) ** 2.2
            rgba = _add_color(rgba, (0.47, 0.93, 0.94), halo * 0.42)
            rgba = _add_color(rgba, (0.58, 0.67, 1.00), halo * 0.190 * _smoothstep(0.12, 0.68, x))
            rgba = _add_color(rgba, (1.00, 0.70, 0.90), halo * 0.150 * _smoothstep(0.12, 0.58, 1.0 - x))

            for blob_cx, blob_cy, blob_rx, blob_ry, color, strength in [
                (-0.06, 0.16, 0.58, 0.14, (1.00, 0.66, 0.88), 0.130),
                (0.10, 0.25, 0.62, 0.18, (0.55, 0.96, 1.00), 0.110),
                (0.00, 0.55, 0.62, 0.20, (0.60, 0.94, 1.00), 0.145),
                (0.30, 0.64, 0.52, 0.18, (0.78, 0.70, 1.00), 0.095),
                (0.24, 0.72, 0.48, 0.16, (1.00, 0.70, 0.90), 0.082),
            ]:
                blob_r = math.sqrt(((x - blob_cx) / blob_rx) ** 2 + ((y - blob_cy) / blob_ry) ** 2)
                blob = max(0.0, 1.0 - blob_r) ** 2.0
                rgba = _add_color(rgba, color, blob * strength)

            # A broad, reference-like diagonal prism film that travels through
            # the lower half of the sidebar. This is the missing "material"
            # layer; it should be readable, but never look like a banner.
            film_center = 0.34 + 0.46 * x
            film_distance = abs(y - film_center)
            broad_film = math.exp(-(film_distance**2) / (2 * 0.038**2))
            broad_gate = _smoothstep(0.08, 0.24, y) * (1.0 - _smoothstep(0.88, 1.00, y))
            lateral_gate = 1.0 - _smoothstep(0.72, 1.02, x)
            rgba = _add_color(rgba, (0.56, 0.96, 1.00), broad_film * broad_gate * lateral_gate * 0.360)
            rgba = _add_color(
                rgba, (0.82, 0.74, 1.00), broad_film * broad_gate * lateral_gate * _smoothstep(0.18, 0.62, x) * 0.245
            )
            rgba = _add_color(
                rgba, (1.00, 0.72, 0.90), broad_film * broad_gate * lateral_gate * _smoothstep(0.28, 0.76, x) * 0.225
            )

            high_film_center = 0.18 + 0.44 * x
            high_film_distance = abs(y - high_film_center)
            high_film = math.exp(-(high_film_distance**2) / (2 * 0.046**2))
            high_gate = _smoothstep(0.06, 0.22, y) * (1.0 - _smoothstep(0.66, 0.84, y))
            rgba = _add_color(rgba, (0.63, 0.98, 0.98), high_film * high_gate * lateral_gate * 0.140)
            rgba = _add_color(
                rgba, (1.00, 0.76, 0.92), high_film * high_gate * lateral_gate * _smoothstep(0.20, 0.70, x) * 0.118
            )

            top_blush_center = 0.145 + 0.24 * x
            top_blush_distance = abs(y - top_blush_center)
            top_blush = math.exp(-(top_blush_distance**2) / (2 * 0.060**2))
            top_gate = (
                _smoothstep(0.08, 0.16, y) * (1.0 - _smoothstep(0.34, 0.48, y)) * (1.0 - _smoothstep(0.62, 0.88, x))
            )
            rgba = _add_color(rgba, (1.00, 0.68, 0.88), top_blush * top_gate * 0.155)
            rgba = _add_color(rgba, (0.62, 0.96, 1.00), top_blush * top_gate * 0.118)

            soft_underlay = math.exp(-(film_distance**2) / (2 * 0.105**2))
            rgba = _add_color(rgba, (0.70, 0.98, 0.98), soft_underlay * broad_gate * lateral_gate * 0.052)

            # Caustic arcs: separated radii sell the thin-film rainbow split
            # better than one generic conic gradient.
            for index, (offset, color, strength) in enumerate(arc_specs):
                arc_radius = math.sqrt(
                    ((x - (cx + 0.02 * math.sin(index))) / (rx + offset)) ** 2 + ((y - cy) / (ry + offset * 0.42)) ** 2
                )
                band = math.exp(-((arc_radius - 0.92 - index * 0.010) ** 2) / (2 * 0.010**2))
                gate = _smoothstep(0.07, 0.36, x) * (1.0 - _smoothstep(0.72, 0.96, x))
                gate *= 1.0 - _smoothstep(0.94, 1.0, y)
                rgba = _add_color(rgba, color, band * gate * strength * 1.70)

            # Diagonal film beams, very low opacity so the sidebar still reads
            # as native glass rather than a decorative illustration.
            for intercept, slope, start_y, thickness, color, strength in beam_specs:
                line = y - (intercept + slope * x)
                beam = math.exp(-(line**2) / (2 * thickness**2))
                gate = _smoothstep(start_y - 0.15, start_y + 0.03, y) * (1.0 - _smoothstep(1.00, 1.06, y))
                taper = 1.0 - _smoothstep(0.58, 0.98, x)
                rgba = _add_color(rgba, color, beam * gate * taper * strength * 1.45)

            # Deterministic micro shimmer breaks up the synthetic surface.
            noise = (
                math.sin((x * 93.0 + y * 41.0 + seed) * math.tau) * 0.010
                + math.sin((x * 17.0 - y * 67.0 + 1.7) * math.tau) * 0.007
                + math.sin((x * 7.0 + y * 11.0 + 0.31) * math.tau) * 0.005
            )
            shimmer = _clamp(halo * 0.55 + max(0.0, 0.98 - y) * 0.016 + noise)
            rgba = _add_color(rgba, (1.0, 1.0, 1.0), shimmer * 0.035)

            red, green, blue, alpha = rgba
            if alpha > 1e-6:
                red /= alpha
                green /= alpha
                blue /= alpha
            pixels.append(
                (
                    int(_clamp(red) * 255),
                    int(_clamp(green) * 255),
                    int(_clamp(blue) * 255),
                    int(_clamp(alpha, 0.0, 1.0) * 255),
                )
            )

    out = Image.new("RGBA", (width, height))
    out.putdata(cast(Any, pixels))
    out = out.filter(ImageFilter.GaussianBlur(radius=1.0))

    film = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    film_draw = ImageDraw.Draw(film)

    def _ribbon_points(offset_y: float, bend: float) -> list[tuple[float, float]]:
        """Return a curved ribbon path for the translucent prism film layer."""
        points: list[tuple[float, float]] = []
        for step in range(90):
            t = step / 89
            x0 = -0.16 * width
            y0 = (0.31 + offset_y) * height
            x1 = 0.38 * width
            y1 = (0.54 + offset_y + bend * 0.22) * height
            x2 = 0.95 * width
            y2 = (0.80 + offset_y + bend) * height
            bx = (1 - t) ** 2 * x0 + 2 * (1 - t) * t * x1 + t**2 * x2
            by = (1 - t) ** 2 * y0 + 2 * (1 - t) * t * y1 + t**2 * y2
            points.append((bx, by))
        return points

    # Wide color films: these are intentionally not hairlines. They create the
    # soft cyan/pink/yellow refraction visible through the sidebar glass.
    for offset, bend, color, width_px in [
        (-0.050, -0.050, (82, 238, 238, 178), 108),
        (-0.020, -0.020, (126, 162, 255, 128), 98),
        (0.010, 0.010, (255, 148, 216, 132), 92),
        (0.040, 0.030, (255, 224, 108, 82), 84),
    ]:
        film_draw.line(_ribbon_points(offset, bend), fill=color, width=width_px, joint="curve")
    film = film.filter(ImageFilter.GaussianBlur(radius=34))
    out = Image.alpha_composite(out, film)

    # A few controlled bright hairlines on top of the blurred color field.
    hairline = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(hairline)
    for index in range(12):
        start_x = rng.uniform(-0.24, 0.12) * width
        start_y = rng.uniform(0.42, 0.88) * height
        end_x = rng.uniform(0.42, 0.90) * width
        end_y = min(height * 1.04, start_y + rng.uniform(0.18, 0.35) * height)
        ctrl_x = rng.uniform(0.10, 0.38) * width
        ctrl_y = min(height * 1.00, start_y + rng.uniform(0.04, 0.16) * height)
        points: list[tuple[float, float]] = []
        for step in range(54):
            t = step / 53
            bx = (1 - t) ** 2 * start_x + 2 * (1 - t) * t * ctrl_x + t**2 * end_x
            by = (1 - t) ** 2 * start_y + 2 * (1 - t) * t * ctrl_y + t**2 * end_y
            points.append((bx, by))
        alpha = int(rng.uniform(18, 34))
        color = rng.choice(
            [(118, 235, 235, alpha), (174, 166, 255, alpha), (255, 188, 222, alpha), (255, 255, 255, alpha)]
        )
        draw.line(points, fill=color, width=rng.choice([1, 1, 2]), joint="curve")
    hairline = hairline.filter(ImageFilter.GaussianBlur(radius=0.45))
    out = Image.alpha_composite(out, hairline)
    red, green, blue, alpha = out.split()
    alpha = alpha.point(lambda value: min(255, int(value * 1.75)))
    return Image.merge("RGBA", (red, green, blue, alpha))


def main() -> None:
    """Render the deterministic prism PNG into the macOS capture resources."""
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    image = _generate_caustic()
    image.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
