"""Typing-focused audit rules for public Python boundaries."""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path

from .ast_helpers import (
    annotation_contains_any,
    annotation_is_bare_collection,
    annotation_is_dict_any,
    annotation_label,
    function_arguments,
    is_public_function,
    is_test_path,
    is_typed_data_class,
    iter_node_annotations,
)
from .models import AuditConfig, FindingSeverity, QualityFinding, make_finding


def typing_findings(
    repo_root: Path,
    file_path: Path,
    tree: ast.Module,
    lines: Sequence[str],
    config: AuditConfig,
) -> list[QualityFinding]:
    """Collect typing drift findings for one parsed file.

    Args:
        repo_root: Repository root used for relative finding paths.
        file_path: File currently being audited.
        tree: Parsed module AST.
        lines: Source lines for comment-based rules.
        config: Audit configuration toggles.

    Returns:
        Typing-related findings for public boundaries and model fields.
    """

    if not config.enable_typing_checks:
        return []
    if is_test_path(file_path) and not config.require_test_typing:
        return []

    findings: list[QualityFinding] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and is_public_function(node):
            findings.extend(_function_typing_findings(repo_root, file_path, node))
        if isinstance(node, ast.ClassDef):
            findings.extend(_class_typing_findings(repo_root, file_path, node))
        for annotation, line_number in iter_node_annotations(node):
            findings.extend(_annotation_typing_findings(repo_root, file_path, annotation, line_number))
    findings.extend(_type_ignore_findings(repo_root, file_path, lines))
    return findings


def _function_typing_findings(
    repo_root: Path,
    file_path: Path,
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    for argument in function_arguments(node):
        if argument.arg in {"self", "cls"} or argument.arg.startswith("_"):
            continue
        if argument.annotation is None:
            findings.append(
                make_finding(
                    repo_root,
                    file_path,
                    argument.lineno,
                    FindingSeverity.WARNING,
                    "typing.argument_missing",
                    f"Public function parameter '{argument.arg}' should have an explicit type annotation.",
                )
            )
    if node.args.vararg is not None and node.args.vararg.annotation is None:
        findings.append(
            make_finding(
                repo_root,
                file_path,
                node.args.vararg.lineno,
                FindingSeverity.WARNING,
                "typing.vararg_missing",
                f"Public function *{node.args.vararg.arg} should have an explicit type annotation.",
            )
        )
    if node.args.kwarg is not None and node.args.kwarg.annotation is None:
        findings.append(
            make_finding(
                repo_root,
                file_path,
                node.args.kwarg.lineno,
                FindingSeverity.WARNING,
                "typing.kwarg_missing",
                f"Public function **{node.args.kwarg.arg} should have an explicit type annotation.",
            )
        )
    if node.returns is None:
        findings.append(
            make_finding(
                repo_root,
                file_path,
                node.lineno,
                FindingSeverity.WARNING,
                "typing.return_missing",
                "Public function should declare a return type, including -> None for side-effect-only APIs.",
            )
        )
    return findings


def _class_typing_findings(repo_root: Path, file_path: Path, node: ast.ClassDef) -> list[QualityFinding]:
    if node.name.startswith("_"):
        return []

    findings: list[QualityFinding] = []
    if not is_typed_data_class(node):
        return findings

    for body_item in node.body:
        if isinstance(body_item, ast.Assign):
            for target in body_item.targets:
                if isinstance(target, ast.Name) and not target.id.startswith("_"):
                    findings.append(
                        make_finding(
                            repo_root,
                            file_path,
                            body_item.lineno,
                            FindingSeverity.WARNING,
                            "typing.model_field_missing",
                            f"Typed data/model field '{target.id}' should use an annotated assignment.",
                        )
                    )
    return findings


def _annotation_typing_findings(
    repo_root: Path,
    file_path: Path,
    annotation: ast.AST,
    line_number: int,
) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    if annotation_is_dict_any(annotation):
        findings.append(
            make_finding(
                repo_root,
                file_path,
                line_number,
                FindingSeverity.WARNING,
                "typing.dict_any_boundary",
                "dict[str, Any] exposes a loose payload boundary; prefer a typed dataclass, BaseModel, or Protocol.",
            )
        )
    if annotation_contains_any(annotation):
        findings.append(
            make_finding(
                repo_root,
                file_path,
                line_number,
                FindingSeverity.WARNING,
                "typing.any_usage",
                f"Annotation '{annotation_label(annotation)}' uses Any; prefer a typed protocol/model or narrower union.",
            )
        )
    if annotation_is_bare_collection(annotation):
        findings.append(
            make_finding(
                repo_root,
                file_path,
                line_number,
                FindingSeverity.WARNING,
                "typing.bare_collection",
                f"Annotation '{annotation_label(annotation)}' should specify element types.",
            )
        )
    return findings


def _type_ignore_findings(repo_root: Path, file_path: Path, lines: Sequence[str]) -> list[QualityFinding]:
    findings: list[QualityFinding] = []
    for line_number, line in enumerate(lines, start=1):
        comment_start = line.find("#")
        if comment_start < 0:
            continue
        normalized = line[comment_start:].lower()
        if "type: ignore" not in normalized:
            continue
        if "[" in normalized and "]" in normalized:
            continue
        findings.append(
            make_finding(
                repo_root,
                file_path,
                line_number,
                FindingSeverity.WARNING,
                "typing.type_ignore_without_code",
                "type: ignore should include a concrete error code so suppressions stay reviewable.",
            )
        )
    return findings
