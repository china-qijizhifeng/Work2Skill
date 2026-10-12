from __future__ import annotations

from pathlib import Path

from scripts.audit_swift_quality import SwiftAuditConfig, audit_swift_sources


def _audit(root: Path, *, max_file: int = 50, max_type: int = 50, max_function: int = 50):
    return audit_swift_sources(
        SwiftAuditConfig(
            root=root,
            max_file_lines=max_file,
            max_type_lines=max_type,
            max_function_lines=max_function,
        )
    )


def test_swift_audit_accepts_small_well_factored_file(tmp_path: Path) -> None:
    (tmp_path / "Good.swift").write_text("""
import Foundation

struct GoodViewModel {
    func title() -> String {
        "WorkRecorder"
    }
}
""".strip())

    assert _audit(tmp_path) == []


def test_swift_audit_reports_oversized_file(tmp_path: Path) -> None:
    (tmp_path / "Large.swift").write_text("\n".join(["// line"] * 6))

    findings = _audit(tmp_path, max_file=5)

    assert [finding.code for finding in findings] == ["swift.file.too_long"]


def test_swift_audit_reports_oversized_type(tmp_path: Path) -> None:
    (tmp_path / "LargeType.swift").write_text("""
final class LargeType {
    let a = 1
    let b = 2
    let c = 3
    let d = 4
}
""".strip())

    findings = _audit(tmp_path, max_type=4)

    assert [finding.code for finding in findings] == ["swift.type.too_long"]


def test_swift_audit_reports_oversized_function(tmp_path: Path) -> None:
    (tmp_path / "LargeFunction.swift").write_text("""
struct Presenter {
    func render() {
        let a = 1
        let b = 2
        let c = 3
        _ = a + b + c
    }
}
""".strip())

    findings = _audit(tmp_path, max_function=4)

    assert [finding.code for finding in findings] == ["swift.function.too_long"]


def test_swift_audit_blocks_page_rendering_in_workbench_controller_file(tmp_path: Path) -> None:
    (tmp_path / "WorkbenchWindowController+Rendering.swift").write_text("""
extension WorkbenchWindowController {
    func renderOverview() {
    }
}
""".strip())

    findings = _audit(tmp_path)

    assert [finding.code for finding in findings] == ["swift.workbench.controller_page_rendering"]


def test_swift_audit_ignores_swift_package_build_outputs(tmp_path: Path) -> None:
    build_dir = tmp_path / ".build" / "debug"
    build_dir.mkdir(parents=True)
    (build_dir / "Generated.swift").write_text("\n".join(["// generated"] * 100))

    assert _audit(tmp_path, max_file=5) == []
