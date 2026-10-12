"""System surface detection for capture attempts."""

from __future__ import annotations

from packages.contracts import (
    BoundingBox,
    CaptureAttemptRequest,
    CaptureStrategy,
    DetectedSurface,
    SurfaceDetectionResult,
    SurfaceKind,
    WindowHint,
)

DESKTOP_APP_NAME = "桌面"
DESKTOP_SURFACE_ID = "surface_desktop"
DESKTOP_TITLE = "桌面区域"
WEB_APP_MARKERS = ("chrome", "edge", "arc")


class SurfaceDetectionService:
    """Rank app/window surfaces overlapped by a user capture selection."""

    def detect(self, attempt: CaptureAttemptRequest) -> SurfaceDetectionResult:
        """Return ranked surfaces from shell-provided window hints.

        Args:
            attempt: Capture attempt carrying OS window/source hints.

        Returns:
            Ranked surface detection result for provider routing.
        """

        hints = tuple(attempt.window_hints)
        if attempt.trigger.capture_strategy == CaptureStrategy.OS_WINDOW:
            primary = self._primary_window_hint(hints)
            hints = (primary,) if primary is not None else ()
        surfaces = tuple(self._surface_from_hint(index, hint) for index, hint in enumerate(hints))
        if not surfaces:
            surfaces = (self._desktop_surface(attempt.selection_geometry.selected_region),)
        ranked = tuple(sorted(surfaces, key=self._surface_sort_key, reverse=True))
        selected = ranked[0].surface_id if ranked else None
        return SurfaceDetectionResult(
            trigger_id=attempt.trigger.trigger_id,
            surfaces=ranked,
            selected_surface_id=selected,
        )

    @classmethod
    def has_valid_os_window_hint(cls, hints: tuple[WindowHint, ...]) -> bool:
        return any(cls._is_valid_os_window_hint(hint) for hint in hints)

    @classmethod
    def primary_os_window_hint(cls, hints: tuple[WindowHint, ...]) -> WindowHint | None:
        for hint in hints:
            if cls._is_valid_os_window_hint(hint):
                return hint
        return None

    def _primary_window_hint(self, hints: tuple[WindowHint, ...]) -> WindowHint | None:
        """Return the shell-declared frontmost window for OS_WINDOW captures.

        Current-App/Appshot capture is already a precise shell decision. Routing
        should not let overlapping background windows compete with the declared
        primary target.
        """

        return self.primary_os_window_hint(hints)

    @staticmethod
    def _is_valid_os_window_hint(hint: WindowHint) -> bool:
        return bool(
            hint.is_frontmost
            and hint.overlap_ratio >= 0.95
            and hint.frame is not None
            and hint.process_id is not None
            and hint.window_id is not None
            and hint.bundle_id is not None
            and hint.display_id is not None
        )

    def _surface_from_hint(self, index: int, hint: WindowHint) -> DetectedSurface:
        confidence = min(1.0, max(0.0, (hint.confidence * 0.7) + (hint.overlap_ratio * 0.3)))
        return DetectedSurface(
            surface_id=f"surface_{index}",
            kind=self._surface_kind(hint).value,
            app_name=hint.app_name,
            title=hint.title,
            process_id=hint.process_id,
            window_id=hint.window_id,
            bundle_id=hint.bundle_id,
            bundle_url=None,
            window_layer=hint.window_layer,
            window_order=hint.window_order,
            display_id=hint.display_id,
            visible_area_ratio=hint.visible_area_ratio,
            is_frontmost=hint.is_frontmost,
            app_icon_ref=hint.app_icon_ref,
            frame=hint.frame,
            overlap_ratio=hint.overlap_ratio,
            confidence=confidence,
            capabilities=(),
        )

    def _surface_score(self, surface: DetectedSurface) -> float:
        """Rank primary surfaces with overlap first, confidence second.

        Swift already sends hints in its best-known z-order/overlap order. This
        score keeps that ordering stable for close candidates while preventing a
        high-confidence frontmost app with tiny bbox overlap from stealing
        primary ownership from the app actually under the user's selection.
        """

        visible_ratio = surface.visible_area_ratio or 0.0
        frontmost_bonus = 0.03 if surface.is_frontmost else 0.0
        z_order_bonus = 0.0
        if surface.window_order is not None:
            z_order_bonus = max(0.0, 0.04 - (surface.window_order * 0.002))
        return min(
            1.0,
            max(
                0.0,
                (surface.overlap_ratio * 0.58)
                + (surface.confidence * 0.31)
                + (visible_ratio * 0.06)
                + frontmost_bonus
                + z_order_bonus,
            ),
        )

    def _surface_sort_key(self, surface: DetectedSurface) -> tuple[float, bool, int, float, float]:
        """Return deterministic primary-source ordering.

        Overlap still dominates, but when multiple stacked windows fully cover
        the selected bbox we must use the compositor z-order. Otherwise a
        slightly larger background window can steal ownership from the visible
        app the user actually captured.
        """

        window_order = surface.window_order if surface.window_order is not None else 1_000_000
        return (
            round(surface.overlap_ratio, 3),
            bool(surface.is_frontmost),
            -window_order,
            surface.confidence,
            surface.visible_area_ratio or 0.0,
        )

    def _desktop_surface(self, selection: BoundingBox) -> DetectedSurface:
        return DetectedSurface(
            surface_id=DESKTOP_SURFACE_ID,
            kind=SurfaceKind.DESKTOP_WINDOW.value,
            app_name=DESKTOP_APP_NAME,
            title=DESKTOP_TITLE,
            process_id=None,
            window_id=None,
            bundle_id=None,
            bundle_url=None,
            window_layer=None,
            window_order=None,
            display_id=selection.coordinate_space.value,
            visible_area_ratio=1.0,
            is_frontmost=False,
            app_icon_ref=None,
            frame=selection,
            overlap_ratio=1.0,
            confidence=0.68,
            capabilities=(),
        )

    def _surface_kind(self, hint: WindowHint) -> SurfaceKind:
        normalized = hint.app_name.strip().lower()
        return (
            SurfaceKind.WEB_BROWSER
            if any(marker in normalized for marker in WEB_APP_MARKERS)
            else SurfaceKind.DESKTOP_WINDOW
        )
