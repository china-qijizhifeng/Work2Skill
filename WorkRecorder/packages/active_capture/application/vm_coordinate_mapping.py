"""Map macOS click coordinates into VM screen coordinates.

The VM is shown inside a VNC / screen-share window on the Mac. A captured click is
in macOS global points, while the VM accessibility tree reports VM screen
coordinates. The window renders the VM screen at a uniform scale, centered
(letterboxed) below the window title bar. This converts a macOS point into the
VM coordinate underneath it so the click can be resolved to a VM element.
"""

from __future__ import annotations

from dataclasses import dataclass

from packages.contracts import BoundingBox

DEFAULT_TITLE_BAR_PT = 28.0


@dataclass(frozen=True)
class VMDisplayGeometry:
    """Static VM screen geometry needed to map macOS clicks into VM coordinates."""

    vm_width: int
    vm_height: int
    title_bar_pt: float = DEFAULT_TITLE_BAR_PT


@dataclass(frozen=True)
class VMDisplayMapping:
    """Affine mapping from macOS points to VM screen coordinates."""

    scale: float
    offset_x: float
    offset_y: float
    vm_width: int
    vm_height: int

    def map_point(self, mac_x: float, mac_y: float) -> tuple[float, float] | None:
        """Return the VM coordinate under a macOS point, or None if outside the VM screen."""

        if self.scale <= 0:
            return None
        vm_x = (mac_x - self.offset_x) / self.scale
        vm_y = (mac_y - self.offset_y) / self.scale
        if vm_x < 0 or vm_y < 0 or vm_x > self.vm_width or vm_y > self.vm_height:
            return None
        return vm_x, vm_y


def build_vm_display_mapping(
    *,
    window_bounds: BoundingBox,
    vm_width: int,
    vm_height: int,
    title_bar_pt: float = DEFAULT_TITLE_BAR_PT,
) -> VMDisplayMapping | None:
    """Derive the macOS->VM mapping for a VNC window showing the VM screen.

    Args:
        window_bounds: VNC window frame in macOS points (from the recording scope).
        vm_width: VM screen width in pixels.
        vm_height: VM screen height in pixels.
        title_bar_pt: Window title bar height in macOS points.

    Returns:
        The mapping, or None when the inputs cannot describe a visible content area.
    """

    if vm_width <= 0 or vm_height <= 0:
        return None
    content_width = window_bounds.width
    content_height = window_bounds.height - title_bar_pt
    if content_width <= 0 or content_height <= 0:
        return None
    scale = min(content_width / vm_width, content_height / vm_height)
    if scale <= 0:
        return None
    rendered_width = vm_width * scale
    rendered_height = vm_height * scale
    offset_x = window_bounds.x + (content_width - rendered_width) / 2
    offset_y = window_bounds.y + title_bar_pt + (content_height - rendered_height) / 2
    return VMDisplayMapping(
        scale=scale,
        offset_x=offset_x,
        offset_y=offset_y,
        vm_width=vm_width,
        vm_height=vm_height,
    )
