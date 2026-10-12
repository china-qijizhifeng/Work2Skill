"""Geometry helpers for click target resolution."""

from __future__ import annotations

from typing import cast

from packages.contracts import ActionPoint, BoundingBox


class ClickGeometry:
    """Pure geometry operations used by providers and scoring."""

    @staticmethod
    def contains(point: ActionPoint, bbox: BoundingBox) -> bool:
        return bbox.x <= point.x <= bbox.x + bbox.width and bbox.y <= point.y <= bbox.y + bbox.height

    @staticmethod
    def area(bbox: BoundingBox) -> int:
        return bbox.width * bbox.height

    @staticmethod
    def center_distance(point: ActionPoint, bbox: BoundingBox) -> float:
        center_x = bbox.x + bbox.width / 2
        center_y = bbox.y + bbox.height / 2
        return cast(float, ((point.x - center_x) ** 2 + (point.y - center_y) ** 2) ** 0.5)

    @staticmethod
    def normalized_distance_score(point: ActionPoint, bbox: BoundingBox) -> float:
        diagonal = max((bbox.width**2 + bbox.height**2) ** 0.5, 1.0)
        distance = ClickGeometry.center_distance(point, bbox)
        return cast(float, max(0.0, min(1.0, 1.0 - distance / diagonal)))
