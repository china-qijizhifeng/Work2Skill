"""Recording scope matching for active capture bindings."""

from __future__ import annotations

from packages.contracts import BoundingBox, CaptureAttemptRequest, RecordingScope, RecordingScopeKind

MIN_REGION_OVERLAP_RATIO = 0.8
SCALE_FACTOR_TOLERANCE = 0.05


class RecordingScopeMatcher:
    """Conservative matcher that keeps scoped sessions from accepting unrelated captures."""

    def matches(self, scope: RecordingScope | None, attempt: CaptureAttemptRequest) -> bool:
        if scope is None:
            return True
        if not self._scope_is_actionable(scope):
            return False
        if scope.kind == RecordingScopeKind.REGION:
            return self._region_matches(scope, attempt)
        if scope.kind == RecordingScopeKind.WINDOW:
            return self._window_scope_matches(scope, attempt)
        return False

    def _region_matches(self, scope: RecordingScope, attempt: CaptureAttemptRequest) -> bool:
        """Match region recordings by the selected capture area, not volatile window titles."""

        return (
            self._region_display_matches(scope, attempt)
            and self._scale_matches(scope, attempt)
            and self._selection_region_matches(scope, attempt)
        )

    def _window_scope_matches(self, scope: RecordingScope, attempt: CaptureAttemptRequest) -> bool:
        return (
            self._display_matches(scope, attempt)
            and self._window_matches(scope, attempt)
            and self._process_matches(scope, attempt)
            and self._bundle_matches(scope, attempt)
            and self._app_matches(scope, attempt)
            and self._title_matches(scope, attempt)
            and self._scale_matches(scope, attempt)
            and self._bounds_match(scope, attempt)
            and self._selection_region_matches(scope, attempt)
        )

    def _scope_is_actionable(self, scope: RecordingScope) -> bool:
        if scope.kind == RecordingScopeKind.WINDOW:
            return bool(scope.window_id or scope.process_id or scope.bundle_id) and scope.bounds is not None
        if scope.kind == RecordingScopeKind.REGION:
            return scope.display_id is not None and scope.selection_region is not None
        return False

    def _display_matches(self, scope: RecordingScope, attempt: CaptureAttemptRequest) -> bool:
        if scope.display_id is None:
            return True
        if attempt.selection_geometry.display.display_id == scope.display_id:
            return True
        return any(hint.display_id == scope.display_id for hint in attempt.window_hints)

    def _region_display_matches(self, scope: RecordingScope, attempt: CaptureAttemptRequest) -> bool:
        if scope.display_id is None:
            return True
        return attempt.selection_geometry.display.display_id == scope.display_id

    def _window_matches(self, scope: RecordingScope, attempt: CaptureAttemptRequest) -> bool:
        if scope.window_id is None:
            return True
        if attempt.trigger.surface_id == scope.window_id:
            return True
        return any(hint.window_id == scope.window_id for hint in attempt.window_hints)

    def _process_matches(self, scope: RecordingScope, attempt: CaptureAttemptRequest) -> bool:
        if scope.process_id is None:
            return True
        return any(hint.process_id == scope.process_id for hint in attempt.window_hints)

    def _bundle_matches(self, scope: RecordingScope, attempt: CaptureAttemptRequest) -> bool:
        if scope.bundle_id is None:
            return True
        return any(hint.bundle_id == scope.bundle_id for hint in attempt.window_hints)

    def _app_matches(self, scope: RecordingScope, attempt: CaptureAttemptRequest) -> bool:
        if scope.app_name is None:
            return True
        expected = scope.app_name.casefold()
        return any(hint.app_name.casefold() == expected for hint in attempt.window_hints)

    def _title_matches(self, scope: RecordingScope, attempt: CaptureAttemptRequest) -> bool:
        if scope.title is None:
            return True
        expected = scope.title.casefold()
        return any(hint.title is not None and hint.title.casefold() == expected for hint in attempt.window_hints)

    def _scale_matches(self, scope: RecordingScope, attempt: CaptureAttemptRequest) -> bool:
        if scope.scale_factor is None:
            return True
        return abs(attempt.selection_geometry.display.scale_factor - scope.scale_factor) <= SCALE_FACTOR_TOLERANCE

    def _bounds_match(self, scope: RecordingScope, attempt: CaptureAttemptRequest) -> bool:
        if scope.bounds is None:
            return True
        candidates = tuple(hint.frame for hint in attempt.window_hints if hint.frame is not None)
        if scope.kind == RecordingScopeKind.REGION:
            candidates = (*candidates, attempt.selection_geometry.selected_region)
        return any(self._overlap_ratio(scope.bounds, candidate) >= MIN_REGION_OVERLAP_RATIO for candidate in candidates)

    def _selection_region_matches(self, scope: RecordingScope, attempt: CaptureAttemptRequest) -> bool:
        if scope.selection_region is None:
            return True
        return (
            self._overlap_ratio(scope.selection_region, attempt.selection_geometry.selected_region)
            >= MIN_REGION_OVERLAP_RATIO
        )

    def _overlap_ratio(self, expected: BoundingBox, observed: BoundingBox) -> float:
        left = max(expected.x, observed.x)
        top = max(expected.y, observed.y)
        right = min(expected.x + expected.width, observed.x + observed.width)
        bottom = min(expected.y + expected.height, observed.y + observed.height)
        if right <= left or bottom <= top:
            return 0.0
        intersection = (right - left) * (bottom - top)
        expected_area = expected.width * expected.height
        return intersection / expected_area
