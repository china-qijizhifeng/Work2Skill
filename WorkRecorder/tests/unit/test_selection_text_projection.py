from __future__ import annotations

from packages.contracts import (
    A11yCoverageReport,
    A11yPermissionState,
    A11ySnapshot,
    A11yTextBlock,
    BoundingBox,
    CoordinateSpace,
    SelectionTextProjection,
)
from packages.evidence.selection_text import SelectionTextProjectionConfig, SelectionTextProjectionService


def test_repeated_labels_in_different_controls_are_preserved():
    projection = _project(
        _block("Edit", "AXButton", 10, 10, 40, 20, node_path="0/0", order_index=0),
        _block("Edit", "AXButton", 80, 10, 40, 20, node_path="0/1", order_index=1),
    )

    assert projection.text == "Edit\nEdit"
    assert projection.block_count == 2


def test_duplicate_same_node_frame_text_is_deduped():
    projection = _project(
        _block("Budget variance +18%", "AXStaticText", 10, 10, 180, 20, node_path="0/0", order_index=0),
        _block("Budget variance +18%", "AXStaticText", 10, 10, 180, 20, node_path="0/0", order_index=1),
    )

    assert projection.text == "Budget variance +18%"
    assert projection.block_count == 1


def test_parent_child_same_text_prefers_leaf_block():
    projection = _project(
        _block(
            "Save",
            "AXButton",
            10,
            10,
            80,
            28,
            node_path="0",
            order_index=0,
            is_leaf_text=False,
        ),
        _block("Save", "AXStaticText", 10, 10, 80, 28, node_path="0/0", order_index=1),
    )

    assert projection.text == "Save"
    assert projection.blocks[0].source_block_id == "block_1"
    assert projection.block_count == 1


def test_overbroad_parent_is_not_default_selection_text():
    projection = _project(
        _block(
            "Whole page text that must not leak into a tiny capture preview",
            "AXWebArea",
            0,
            0,
            1200,
            1800,
            node_path="0",
            is_leaf_text=False,
        )
    )

    assert projection.text == ""
    assert projection.overbroad_parent_only is True


def test_overbroad_leaf_text_is_not_default_selection_text():
    projection = _project(
        _block(
            "A very large leaf text object that likely represents the whole document body",
            "AXStaticText",
            0,
            0,
            1800,
            2200,
            node_path="0/0",
            order_index=0,
        )
    )

    assert projection.text == ""
    assert projection.block_count == 0


def test_table_like_blocks_are_ordered_row_major():
    projection = _project(
        _block("Status", "AXCell", 120, 10, 70, 20, node_path="0/1", role_path=("AXTable",), order_index=1),
        _block("Account", "AXCell", 10, 10, 80, 20, node_path="0/0", role_path=("AXTable",), order_index=0),
        _block("Late", "AXCell", 120, 40, 70, 20, node_path="0/3", role_path=("AXTable",), order_index=3),
        _block("ACME", "AXCell", 10, 40, 80, 20, node_path="0/2", role_path=("AXTable",), order_index=2),
    )

    assert projection.text == "Account\nStatus\nACME\nLate"


def test_multicolumn_document_blocks_are_ordered_column_major():
    projection = _project(
        _block("Right top", "AXStaticText", 340, 10, 120, 20, node_path="0/2", order_index=2),
        _block("Left bottom", "AXStaticText", 10, 80, 140, 20, node_path="0/1", order_index=1),
        _block("Left top", "AXStaticText", 10, 10, 120, 20, node_path="0/0", order_index=0),
        _block("Right bottom", "AXStaticText", 340, 80, 140, 20, node_path="0/3", order_index=3),
    )

    assert projection.text == "Left top\nLeft bottom\nRight top\nRight bottom"


def test_edge_recovery_can_admit_nearby_leaf_text():
    selection = BoundingBox(x=20, y=20, width=100, height=40, coordinate_space=CoordinateSpace.MACOS_GLOBAL)
    projection = _project(
        _block("clipped-word", "AXStaticText", 122, 24, 30, 18, node_path="0/0", order_index=0),
        selection=selection,
    )

    assert projection.text == "clipped-word"
    assert projection.blocks[0].edge_recovered is True
    assert projection.confidence < 0.9


def test_text_limits_record_truncation():
    service = SelectionTextProjectionService(config=SelectionTextProjectionConfig(max_blocks=3, max_text_chars=1_000))
    projection = service.project(
        _snapshot(
            *(
                _block(f"Line {index}", "AXStaticText", 10, 10 + index * 24, 80, 20, order_index=index)
                for index in range(5)
            )
        )
    )

    assert projection.truncated is True
    assert projection.truncation_reason == "max_blocks"
    assert projection.text == "Line 0\nLine 1\nLine 2"


def test_sensitive_text_is_redacted_before_projection_output():
    projection = _project(
        _block(
            "API token: SHOULD_NOT_LEAK_VISIBLE_TOKEN",
            "AXStaticText",
            10,
            10,
            260,
            20,
            node_path="0/0",
            order_index=0,
        )
    )

    assert "SHOULD_NOT_LEAK" not in projection.text
    assert projection.text == "API token: [REDACTED]"


def _project(
    *blocks: A11yTextBlock,
    selection: BoundingBox | None = None,
) -> SelectionTextProjection:
    return SelectionTextProjectionService().project(_snapshot(*blocks, selection=selection))


def _snapshot(
    *blocks: A11yTextBlock,
    selection: BoundingBox | None = None,
) -> A11ySnapshot:
    selection = selection or BoundingBox(x=0, y=0, width=520, height=280, coordinate_space=CoordinateSpace.MACOS_GLOBAL)
    return A11ySnapshot(
        permission_state=A11yPermissionState.GRANTED,
        app_name="Google Chrome",
        process_id=4242,
        window_id="win_test",
        selection=selection,
        text_blocks=blocks,
        full_text="\n".join(block.text for block in blocks),
        coverage=A11yCoverageReport(
            selection=selection,
            permission_state=A11yPermissionState.GRANTED,
            node_count=len(blocks),
            text_block_count=len(blocks),
            covered_area_ratio=0.8 if blocks else 0.0,
            confidence=0.9 if blocks else 0.0,
        ),
    )


def _block(
    text: str,
    role: str,
    x: int,
    y: int,
    width: int,
    height: int,
    *,
    node_path: str = "0/0",
    role_path: tuple[str, ...] = (),
    order_index: int = 0,
    is_leaf_text: bool = True,
) -> A11yTextBlock:
    frame = BoundingBox(x=x, y=y, width=width, height=height, coordinate_space=CoordinateSpace.MACOS_GLOBAL)
    return A11yTextBlock(
        text=text,
        block_id=f"block_{order_index}",
        role=role,
        node_path=node_path,
        role_path=role_path,
        text_source="value",
        frame=frame,
        selection_overlap_ratio=1.0,
        element_overlap_ratio=1.0,
        order_index=order_index,
        is_leaf_text=is_leaf_text,
        confidence=0.9,
    )
