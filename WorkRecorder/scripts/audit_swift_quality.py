"""Audit Swift source structure without requiring SwiftLint.

The macOS app has enough surface area now that oversized controller files can
quietly become a maintenance hazard. This audit is intentionally simple and
repository-local: it enforces broad structural limits and catches page rendering
creeping back into Workbench window-controller files.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_EXCLUDES = {".build", ".swiftpm", "DerivedData"}
TYPE_PATTERN = re.compile(
    r"^\s*(?:(?:@\w+(?:\([^)]*\))?)\s*)*"
    r"(?:(?:public|private|fileprivate|internal|open)\s+)?"
    r"(?:(?:final|indirect)\s+)?"
    r"(class|struct|enum|extension|actor|protocol)\s+([A-Za-z_][\w.]*)"
)
FUNCTION_PATTERN = re.compile(
    r"^\s*(?:(?:@\w+(?:\([^)]*\))?)\s*)*"
    r"(?:(?:public|private|fileprivate|internal|open)\s+)?"
    r"(?:(?:static|class|mutating|nonmutating|override|final|convenience|required|nonisolated)\s+)*"
    r"(func|init|deinit|subscript)\b"
)
PAGE_RENDER_PATTERN = re.compile(
    r"^\s*func\s+(render(?:Overview|Onboarding|Practice|Scope|History|Privacy|Diagnostics|ModelSettings|Content)|"
    r"contextLibrary(?:Toolbar|Canvas|CanvasHost|List|EmptyState)|"
    r"recentCaptureSection)\b"
)


@dataclass(frozen=True, slots=True)
class SwiftQualityFinding:
    """One structural Swift quality violation.

    Attributes:
        code: Stable machine-readable finding code.
        path: Repository-relative file path where the finding was detected.
        line: One-based source line for the offending declaration or file.
        message: Human-readable explanation for terminal output.
    """

    code: str
    path: str
    line: int
    message: str


@dataclass(frozen=True, slots=True)
class SwiftAuditConfig:
    """Configuration for one Swift quality audit run.

    Attributes:
        root: Directory tree to scan for Swift source files.
        max_file_lines: Maximum allowed physical lines in one Swift file.
        max_type_lines: Maximum allowed lines in a class, struct, enum, extension, actor, or protocol.
        max_function_lines: Maximum allowed lines in a function, initializer, deinitializer, or subscript.
    """

    root: Path
    max_file_lines: int
    max_type_lines: int
    max_function_lines: int


def build_argument_parser() -> argparse.ArgumentParser:
    """Build the command-line interface for Swift quality auditing.

    Returns:
        Configured parser with threshold and report-output options.
    """

    parser = argparse.ArgumentParser(description="Audit Swift file/type/function size limits.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT / "apps" / "macos_capture")
    parser.add_argument("--max-file-lines", type=int, default=700)
    parser.add_argument("--max-type-lines", type=int, default=450)
    parser.add_argument("--max-function-lines", type=int, default=120)
    parser.add_argument("--json-output", type=Path)
    return parser


def main() -> int:
    """Run the Swift quality audit from command-line arguments.

    Returns:
        Zero when all inspected Swift files satisfy the configured limits; non-zero otherwise.
    """

    args = build_argument_parser().parse_args()
    config = SwiftAuditConfig(
        root=(REPO_ROOT / args.root).resolve() if not args.root.is_absolute() else args.root.resolve(),
        max_file_lines=args.max_file_lines,
        max_type_lines=args.max_type_lines,
        max_function_lines=args.max_function_lines,
    )
    findings = audit_swift_sources(config)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(json.dumps([asdict(f) for f in findings], ensure_ascii=False, indent=2))
    if findings:
        for finding in findings:
            location = f"{finding.path}:{finding.line}"
            print(f"{location}: {finding.code}: {finding.message}", file=sys.stderr)
        print(f"Swift quality audit failed with {len(findings)} finding(s).", file=sys.stderr)
        return 1
    print("Swift quality audit passed.")
    return 0


def audit_swift_sources(config: SwiftAuditConfig) -> list[SwiftQualityFinding]:
    """Inspect Swift files and return structural quality findings.

    Args:
        config: Root path and threshold configuration for the audit.

    Returns:
        Ordered findings for oversized files, declarations, functions, and disallowed Workbench rendering.
    """

    findings: list[SwiftQualityFinding] = []
    for path in iter_swift_files(config.root):
        rel = _relative(path)
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > config.max_file_lines:
            findings.append(
                SwiftQualityFinding(
                    code="swift.file.too_long",
                    path=rel,
                    line=1,
                    message=f"{len(lines)} lines exceeds limit {config.max_file_lines}.",
                )
            )
        stripped_lines = list(strip_swift_noise(lines))
        findings.extend(_audit_declarations(path, rel, stripped_lines, config))
        findings.extend(_audit_workbench_controller_rendering(path, rel, stripped_lines))
    return findings


def iter_swift_files(root: Path) -> Iterable[Path]:
    """Yield Swift source files under a root while skipping generated build folders.

    Args:
        root: Directory tree to scan.

    Returns:
        Iterable over Swift source paths.

    Yields:
        Swift source paths in deterministic lexical order.
    """

    for path in sorted(root.rglob("*.swift")):
        if any(part in DEFAULT_EXCLUDES for part in path.parts):
            continue
        yield path


def strip_swift_noise(lines: list[str]) -> Iterable[str]:
    """Remove comments and string contents before brace counting.

    Args:
        lines: Raw Swift source lines.

    Returns:
        Iterable over normalized Swift source lines.

    Yields:
        Lines with comments and string literal bodies replaced or removed so simple structural parsing is stable.
    """

    in_block_comment = False
    for line in lines:
        output: list[str] = []
        index = 0
        in_string = False
        while index < len(line):
            current = line[index]
            nxt = line[index + 1] if index + 1 < len(line) else ""
            if in_block_comment:
                if current == "*" and nxt == "/":
                    in_block_comment = False
                    index += 2
                else:
                    index += 1
                continue
            if not in_string and current == "/" and nxt == "*":
                in_block_comment = True
                index += 2
                continue
            if not in_string and current == "/" and nxt == "/":
                break
            if current == '"' and (index == 0 or line[index - 1] != "\\"):
                in_string = not in_string
                output.append('"')
            elif in_string:
                output.append(" ")
            else:
                output.append(current)
            index += 1
        yield "".join(output)


def _audit_declarations(
    path: Path,
    rel: str,
    lines: list[str],
    config: SwiftAuditConfig,
) -> list[SwiftQualityFinding]:
    findings: list[SwiftQualityFinding] = []
    for index, line in enumerate(lines):
        type_match = TYPE_PATTERN.match(line)
        if type_match:
            span = _balanced_span(lines, index)
            if span and span.length > config.max_type_lines:
                findings.append(
                    SwiftQualityFinding(
                        code="swift.type.too_long",
                        path=rel,
                        line=index + 1,
                        message=f"{type_match.group(1)} {type_match.group(2)} has {span.length} lines; limit is {config.max_type_lines}.",
                    )
                )
        if FUNCTION_PATTERN.match(line):
            span = _balanced_span(lines, index)
            if span and span.length > config.max_function_lines:
                findings.append(
                    SwiftQualityFinding(
                        code="swift.function.too_long",
                        path=rel,
                        line=index + 1,
                        message=f"function has {span.length} lines; limit is {config.max_function_lines}.",
                    )
                )
    return findings


@dataclass(frozen=True, slots=True)
class BalancedSpan:
    """Inclusive source range for a balanced Swift declaration body.

    Attributes:
        start: Zero-based start line index.
        end: Zero-based end line index.
    """

    start: int
    end: int

    @property
    def length(self) -> int:
        """Return the number of physical source lines in the span.

        Returns:
            Inclusive line count.
        """

        return self.end - self.start + 1


def _balanced_span(lines: list[str], start_index: int) -> BalancedSpan | None:
    depth = 0
    saw_open_brace = False
    for index in range(start_index, len(lines)):
        line = lines[index]
        open_count = line.count("{")
        close_count = line.count("}")
        if open_count:
            saw_open_brace = True
        if saw_open_brace:
            depth += open_count - close_count
            if depth <= 0:
                return BalancedSpan(start=start_index, end=index)
    return None


def _audit_workbench_controller_rendering(
    path: Path,
    rel: str,
    lines: list[str],
) -> list[SwiftQualityFinding]:
    if not path.name.startswith("WorkbenchWindowController"):
        return []
    findings: list[SwiftQualityFinding] = []
    for index, line in enumerate(lines):
        if PAGE_RENDER_PATTERN.match(line):
            findings.append(
                SwiftQualityFinding(
                    code="swift.workbench.controller_page_rendering",
                    path=rel,
                    line=index + 1,
                    message="page-level rendering must live outside WorkbenchWindowController files.",
                )
            )
    return findings


def _relative(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
