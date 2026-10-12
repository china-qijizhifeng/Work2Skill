from __future__ import annotations

from packages.contracts import (
    A11yCoverageReport,
    A11yPermissionState,
    A11ySnapshot,
    A11yTextBlock,
    BoundingBox,
    CoordinateSpace,
)
from packages.evidence.selection_text import SelectionTextProjectionService


def test_long_web_document_ignores_toolbar_and_overbroad_parent():
    projection = _project(
        _block("Browser toolbar SHOULD_NOT_LEAK", "AXToolbar", 0, 80, 1440, 44, 0),
        _block(
            "Whole article body SHOULD_NOT_LEAK",
            "AXWebArea",
            0,
            0,
            1200,
            1800,
            1,
            is_leaf_text=False,
        ),
        _block("Abstract", "AXStaticText", 130, 150, 90, 20, 2),
        _block("WorkRecorder captures context as audit-ready evidence.", "AXStaticText", 130, 182, 390, 36, 3),
        _block("Provider routing selects fresh sessions.", "AXStaticText", 130, 236, 310, 24, 4),
    )

    assert projection.text == (
        "Abstract\n" "WorkRecorder captures context as audit-ready evidence.\n" "Provider routing selects fresh sessions."
    )
    assert "SHOULD_NOT_LEAK" not in projection.text


def test_arxiv_like_two_column_document_uses_column_major_order():
    projection = _project(
        _block("Right column theorem", "AXStaticText", 410, 150, 180, 20, 2),
        _block("Left column abstract", "AXStaticText", 130, 150, 180, 20, 0),
        _block("Left column method", "AXStaticText", 130, 210, 180, 20, 1),
        _block("Right column proof", "AXStaticText", 410, 210, 180, 20, 3),
    )

    assert projection.text == (
        "Left column abstract\n" "Left column method\n" "Right column theorem\n" "Right column proof"
    )


def test_pdf_parent_or_huge_leaf_does_not_become_default_text():
    projection = _project(
        _block(
            "Whole PDF page SHOULD_NOT_LEAK_PDF",
            "AXDocument",
            0,
            0,
            1600,
            2400,
            0,
            is_leaf_text=False,
        ),
        _block(
            "Huge renderer text SHOULD_NOT_LEAK_PDF",
            "AXStaticText",
            0,
            0,
            1600,
            2400,
            1,
        ),
    )

    assert projection.text == ""
    assert projection.block_count == 0


def test_native_app_table_like_blocks_preserve_duplicate_actions():
    projection = _project(
        _block("Project", "AXCell", 130, 150, 90, 20, 0, role_path=("AXTable",)),
        _block("Owner", "AXCell", 250, 150, 80, 20, 1, role_path=("AXTable",)),
        _block("Action", "AXCell", 370, 150, 80, 20, 2, role_path=("AXTable",)),
        _block("WorkRecorder", "AXCell", 130, 190, 110, 20, 3, role_path=("AXTable",)),
        _block("Context SDK", "AXCell", 250, 190, 110, 20, 4, role_path=("AXTable",)),
        _block("Edit", "AXButton", 370, 190, 52, 22, 5, role_path=("AXTable",)),
        _block("Prism", "AXCell", 130, 230, 80, 20, 6, role_path=("AXTable",)),
        _block("Capture App", "AXCell", 250, 230, 110, 20, 7, role_path=("AXTable",)),
        _block("Edit", "AXButton", 370, 230, 52, 22, 8, role_path=("AXTable",)),
    )

    assert projection.text == (
        "Project\n" "Owner\n" "Action\n" "WorkRecorder\n" "Context SDK\n" "Edit\n" "Prism\n" "Capture App\n" "Edit"
    )


def test_slightly_clipped_line_uses_edge_recovery_without_pulling_header():
    selection = BoundingBox(x=120, y=140, width=260, height=80, coordinate_space=CoordinateSpace.MACOS_GLOBAL)
    projection = _project(
        _block("Outside heading", "AXStaticText", 120, 96, 180, 20, 0),
        _block("Renewal status", "AXStaticText", 130, 150, 120, 20, 1),
        _block("medium", "AXStaticText", 381, 150, 40, 20, 2),
        selection=selection,
    )

    assert projection.text == "Renewal status\nmedium"
    assert projection.blocks[-1].edge_recovered is True
    assert "Outside heading" not in projection.text


def _project(*blocks: A11yTextBlock, selection: BoundingBox | None = None):
    return SelectionTextProjectionService().project(_snapshot(*blocks, selection=selection))


def _snapshot(*blocks: A11yTextBlock, selection: BoundingBox | None = None) -> A11ySnapshot:
    selection = selection or BoundingBox(
        x=120, y=140, width=520, height=280, coordinate_space=CoordinateSpace.MACOS_GLOBAL
    )
    return A11ySnapshot(
        permission_state=A11yPermissionState.GRANTED,
        app_name="Realistic QA Surface",
        process_id=4242,
        window_id="win_realistic",
        selection=selection,
        text_blocks=blocks,
        full_text="\n".join(block.text for block in blocks),
        coverage=A11yCoverageReport(
            selection=selection,
            permission_state=A11yPermissionState.GRANTED,
            node_count=len(blocks),
            text_block_count=len(blocks),
            covered_area_ratio=0.82 if blocks else 0.0,
            confidence=0.88 if blocks else 0.0,
        ),
    )


def _block(
    text: str,
    role: str,
    x: int,
    y: int,
    width: int,
    height: int,
    order_index: int,
    *,
    role_path: tuple[str, ...] = (),
    is_leaf_text: bool = True,
) -> A11yTextBlock:
    return A11yTextBlock(
        text=text,
        block_id=f"realistic_block_{order_index}",
        role=role,
        node_path=f"0/{order_index}",
        role_path=role_path + (role,),
        text_source="value",
        frame=BoundingBox(x=x, y=y, width=width, height=height, coordinate_space=CoordinateSpace.MACOS_GLOBAL),
        selection_overlap_ratio=1.0,
        element_overlap_ratio=1.0,
        order_index=order_index,
        is_leaf_text=is_leaf_text,
        confidence=0.9,
    )
