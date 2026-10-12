"""Maintainability and documentation checks for the repository quality audit."""

from __future__ import annotations

import ast
from collections.abc import Iterable, Sequence
from pathlib import Path

from .ast_helpers import (
    class_has_public_fields,
    defines_logger,
    function_has_comment,
    function_has_logging,
    handler_logs,
    handler_reraises_with_context,
    has_any_marker,
    has_attribute_docs,
    has_documentable_parameters,
    imports_logging,
    is_broad_exception_handler,
    is_public_function,
    is_test_path,
    node_line_count,
    raises_exception,
    returns_value,
    uses_module_logging_emitter,
    word_count,
)
from .models import AuditConfig, FindingSeverity, QualityFinding, make_finding


def line_count_findings(repo_root: Path, file_path: Path, line_count: int, config: AuditConfig) -> list[QualityFinding]:
    """Return file length findings for one module.

    Args:
        repo_root: Repository root used for relative finding paths.
        file_path: Source file currently being audited.
        line_count: Effective source line count for the module.
        config: Audit thresholds used to classify the finding.

    Returns:
        Length findings, or an empty list when the file is within budget.
    """

    if is_test_path(file_path):
        return []
    if line_count > config.max_file_lines_violation:
        return [
            make_finding(
                repo_root,
                file_path,
                1,
                FindingSeverity.VIOLATION,
                "module.too_long.violation",
                f"File has {line_count} lines; split below {config.max_file_lines_violation}.",
            )
        ]
    if line_count > config.max_file_lines_warning:
        return [
            make_finding(
                repo_root,
                file_path,
                1,
                FindingSeverity.WARNING,
                "module.too_long.warning",
                f"File has {line_count} lines; target is {config.max_file_lines_warning}.",
            )
        ]
    return []


def module_docstring_findings(
    repo_root: Path,
    file_path: Path,
    tree: ast.Module,
    config: AuditConfig,
) -> list[QualityFinding]:
    """Return module docstring findings for one parsed file.

    Args:
        repo_root: Repository root used for relative finding paths.
        file_path: Source file currently being audited.
        tree: Parsed module AST.
        config: Audit thresholds and test toggles.

    Returns:
        Module docstring findings, or an empty list when documentation is sufficient.
    """

    if is_test_path(file_path) and not config.require_test_docstrings:
        return []
    if file_path.name == "__init__.py" and not tree.body:
        return []
    docstring = ast.get_docstring(tree)
    if docstring and word_count(docstring) >= config.min_docstring_words:
        return []
    return [
        make_finding(
            repo_root,
            file_path,
            1,
            FindingSeverity.WARNING,
            "docstring.module_missing_or_thin",
            "Module should start with a concise docstring explaining its responsibility.",
        )
    ]


def top_level_function_findings(
    repo_root: Path,
    file_path: Path,
    tree: ast.Module,
    config: AuditConfig,
) -> list[QualityFinding]:
    """Return findings for modules drifting toward function bags.

    Args:
        repo_root: Repository root used for relative finding paths.
        file_path: Source file currently being audited.
        tree: Parsed module AST.
        config: Audit thresholds used to classify the finding.

    Returns:
        Top-level function count findings, or an empty list when the module is
        within budget.
    """

    if is_test_path(file_path) or file_path.name == "__init__.py":
        return []
    top_level_functions = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not node.name.startswith("_")
        and not _is_thin_delegating_wrapper(node)
    ]
    function_count = len(top_level_functions)
    if function_count > config.max_top_level_functions_violation:
        return [
            make_finding(
                repo_root,
                file_path,
                top_level_functions[0].lineno if top_level_functions else 1,
                FindingSeverity.VIOLATION,
                "module.too_many_top_level_functions.violation",
                (
                    f"Module exposes {function_count} top-level functions; extract cohesive service/strategy classes "
                    f"or split below {config.max_top_level_functions_violation}."
                ),
            )
        ]
    if function_count > config.max_top_level_functions_warning:
        return [
            make_finding(
                repo_root,
                file_path,
                top_level_functions[0].lineno if top_level_functions else 1,
                FindingSeverity.WARNING,
                "module.too_many_top_level_functions.warning",
                (
                    f"Module exposes {function_count} top-level functions; prefer cohesive service/strategy classes "
                    f"over function bags."
                ),
            )
        ]
    return []


def _is_thin_delegating_wrapper(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    body = [item for item in node.body if not isinstance(item, ast.Expr) or not isinstance(item.value, ast.Constant)]
    if len(body) != 1:
        return False
    statement = body[0]
    if isinstance(statement, ast.Return):
        return isinstance(statement.value, ast.Call)
    if isinstance(statement, ast.Expr):
        return isinstance(statement.value, ast.Call)
    return False


def public_api_docstring_findings(
    repo_root: Path,
    file_path: Path,
    tree: ast.Module,
    lines: Sequence[str],
    config: AuditConfig,
) -> list[QualityFinding]:
    """Return public class/function docstring findings for one parsed file.

    Args:
        repo_root: Repository root used for relative finding paths.
        file_path: Source file currently being audited.
        tree: Parsed module AST.
        lines: Physical source lines used by long-function comment checks.
        config: Audit thresholds and test toggles.

    Returns:
        Public API documentation findings for classes and functions.
    """

    if is_test_path(file_path) and not config.require_test_docstrings:
        return []
    findings: list[QualityFinding] = []
    # Public class methods are documented through the class/protocol contract
    # and by type signatures. Scanning every method as a standalone top-level
    # API creates noisy duplicate findings for cohesive OO services, so this
    # check is intentionally limited to module-level public functions/classes.
    nodes: Iterable[ast.AST] = tree.body
    for node in nodes:
        if isinstance(node, ast.ClassDef):
            findings.extend(_class_findings(repo_root, file_path, node, config))
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and is_public_function(node):
            findings.extend(_function_findings(repo_root, file_path, node, lines, config))
    return findings


def logging_findings(repo_root: Path, file_path: Path, tree: ast.Module) -> list[QualityFinding]:
    """Return logging hygiene findings for one parsed file.

    Args:
        repo_root: Repository root used for relative finding paths.
        file_path: Source file currently being audited.
        tree: Parsed module AST.

    Returns:
        Logging hygiene findings for module loggers and broad handlers.
    """

    findings: list[QualityFinding] = []
    if imports_logging(tree) and uses_module_logging_emitter(tree) and not defines_logger(tree):
        findings.append(
            make_finding(
                repo_root,
                file_path,
                1,
                FindingSeverity.WARNING,
                "logging.logger_missing",
                "Module imports logging but does not define a module-level logger.",
            )
        )
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.ExceptHandler)
            and is_broad_exception_handler(node)
            and not handler_logs(node)
            and not handler_reraises_with_context(node)
        ):
            findings.append(
                make_finding(
                    repo_root,
                    file_path,
                    node.lineno,
                    FindingSeverity.WARNING,
                    "logging.broad_except_without_log",
                    "Broad exception handler should log context or explain why silence is intentional.",
                )
            )
    return findings


def todo_findings(repo_root: Path, file_path: Path, lines: Sequence[str]) -> list[QualityFinding]:
    """Return TODO/FIXME findings for one source file.

    Args:
        repo_root: Repository root used for relative finding paths.
        file_path: Source file currently being audited.
        lines: Physical source lines to scan for debt comments.

    Returns:
        Comment debt findings for TODO and FIXME markers.
    """

    findings: list[QualityFinding] = []
    for line_number, line in enumerate(lines, start=1):
        comment_start = line.find("#")
        if comment_start < 0:
            continue
        normalized = line[comment_start:].lower()
        if "todo" in normalized or "fixme" in normalized:
            findings.append(
                make_finding(
                    repo_root,
                    file_path,
                    line_number,
                    FindingSeverity.WARNING,
                    "comment.todo_or_fixme",
                    "TODO/FIXME should be tracked or resolved before production hardening.",
                )
            )
    return findings


def _class_findings(
    repo_root: Path,
    file_path: Path,
    node: ast.ClassDef,
    config: AuditConfig,
) -> list[QualityFinding]:
    if node.name.startswith("_"):
        return []
    findings: list[QualityFinding] = []
    class_lines = node_line_count(node)
    if class_lines > config.max_class_lines_warning:
        findings.append(
            make_finding(
                repo_root,
                file_path,
                node.lineno,
                FindingSeverity.WARNING,
                "class.too_long",
                f"Class has {class_lines} lines; split responsibilities or extract helpers.",
            )
        )
    docstring = ast.get_docstring(node) or ""
    if word_count(docstring) < config.min_docstring_words:
        findings.append(
            make_finding(
                repo_root,
                file_path,
                node.lineno,
                FindingSeverity.WARNING,
                "docstring.class_missing_or_thin",
                "Public class should explain its role and lifecycle.",
            )
        )
        return findings
    if class_has_public_fields(node) and not has_attribute_docs(docstring):
        findings.append(
            make_finding(
                repo_root,
                file_path,
                node.lineno,
                FindingSeverity.WARNING,
                "docstring.class_attributes_missing",
                "Typed data/model class should document Attributes/Fields so variables are explainable.",
            )
        )
    return findings


def _function_findings(
    repo_root: Path,
    file_path: Path,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    lines: Sequence[str],
    config: AuditConfig,
) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    function_lines = node_line_count(node)
    docstring = ast.get_docstring(node) or ""
    if function_lines > config.max_function_lines_warning:
        findings.append(
            make_finding(
                repo_root,
                file_path,
                node.lineno,
                FindingSeverity.WARNING,
                "function.too_long",
                f"Function has {function_lines} lines; consider extracting a focused helper or strategy class.",
            )
        )
        if not function_has_logging(node) and not function_has_comment(lines, node):
            findings.append(
                make_finding(
                    repo_root,
                    file_path,
                    node.lineno,
                    FindingSeverity.WARNING,
                    "function.long_without_log_or_comment",
                    "Long function has no obvious logging or explanatory comments.",
                )
            )
    if word_count(docstring) < config.min_docstring_words:
        findings.append(
            make_finding(
                repo_root,
                file_path,
                node.lineno,
                FindingSeverity.WARNING,
                "docstring.function_missing_or_thin",
                "Public function should explain behavior, important parameters, and return semantics.",
            )
        )
        return findings
    normalized_docstring = docstring.lower()
    if has_documentable_parameters(node) and not has_any_marker(
        normalized_docstring, ("args:", "arguments:", "parameters:", ":param")
    ):
        findings.append(
            make_finding(
                repo_root,
                file_path,
                node.lineno,
                FindingSeverity.WARNING,
                "docstring.args_missing",
                "Function has public parameters but docstring lacks Args/Parameters detail.",
            )
        )
    if returns_value(node) and not has_any_marker(normalized_docstring, ("returns:", ":returns:", ":return:")):
        findings.append(
            make_finding(
                repo_root,
                file_path,
                node.lineno,
                FindingSeverity.WARNING,
                "docstring.returns_missing",
                "Function returns a value but docstring lacks Returns detail.",
            )
        )
    if raises_exception(node) and not has_any_marker(normalized_docstring, ("raises:", ":raises:", ":raise")):
        findings.append(
            make_finding(
                repo_root,
                file_path,
                node.lineno,
                FindingSeverity.WARNING,
                "docstring.raises_missing",
                "Function raises exceptions but docstring lacks Raises detail.",
            )
        )
    return findings
