from __future__ import annotations

from packages.contracts import BoundingBox
from packages.active_capture.application.vm_coordinate_mapping import (
    build_vm_display_mapping,
    VMDisplayMapping,
)


def _vnc_window() -> BoundingBox:
    # Measured TigerVNC window on a Retina Mac showing a 1380x866 VM screen.
    return BoundingBox(x=0, y=56, width=1512, height=893, coordinate_space="macos_global")


def test_mapping_recovers_measured_offset() -> None:
    mapping = build_vm_display_mapping(window_bounds=_vnc_window(), vm_width=1380, vm_height=866, title_bar_pt=27)
    assert mapping is not None
    # 1:1 in points, centred horizontally (66px each side), title bar 27px.
    assert mapping.scale == 1.0
    assert round(mapping.offset_x) == 66
    assert round(mapping.offset_y) == 83


def test_mapping_translates_mac_click_to_vm_element_center() -> None:
    mapping = build_vm_display_mapping(window_bounds=_vnc_window(), vm_width=1380, vm_height=866, title_bar_pt=27)
    assert mapping is not None
    # A Mac click that should land on the VM "File" button center (91, 107).
    vm = mapping.map_point(91 + 66, 107 + 83)
    assert vm is not None
    assert round(vm[0]) == 91
    assert round(vm[1]) == 107


def test_mapping_rejects_points_outside_vm_screen() -> None:
    mapping = build_vm_display_mapping(window_bounds=_vnc_window(), vm_width=1380, vm_height=866, title_bar_pt=27)
    assert mapping is not None
    # Inside the window title bar (above the VM content) maps outside the VM screen.
    assert mapping.map_point(700, 60) is None
    # Far right of the horizontally centred VM content (in the letterbox margin).
    assert mapping.map_point(1500, 400) is None


def test_mapping_scales_when_window_is_smaller_than_vm() -> None:
    bounds = BoundingBox(x=10, y=40, width=700, height=466, coordinate_space="macos_global")
    mapping = build_vm_display_mapping(window_bounds=bounds, vm_width=1380, vm_height=866, title_bar_pt=28)
    assert mapping is not None
    assert mapping.scale < 1.0
    center = mapping.map_point(mapping.offset_x + 690 / 2, mapping.offset_y + (1380 * mapping.scale) * 0)
    assert center is not None


def test_mapping_returns_none_for_degenerate_inputs() -> None:
    bounds = BoundingBox(x=0, y=0, width=100, height=20, coordinate_space="macos_global")
    assert build_vm_display_mapping(window_bounds=bounds, vm_width=1380, vm_height=866, title_bar_pt=28) is None
    good = _vnc_window()
    assert build_vm_display_mapping(window_bounds=good, vm_width=0, vm_height=866) is None
    assert isinstance(
        build_vm_display_mapping(window_bounds=good, vm_width=1380, vm_height=866), VMDisplayMapping
    )
