"""Docstring and source-span helpers for quality audit rules."""

from __future__ import annotations

import ast
from collections.abc import Sequence
from pathlib import Path

from .ast_names import base_name, decorator_name
from .constants import PUBLIC_CLASS_BASE_NAMES


def is_test_path(file_path: Path) -> bool:
    """Return whether a path belongs to the test suite.

    Args:
        file_path: Path-like object being audited.

    Returns:
        True for paths below tests or named ``test_*``.
    """

    return "tests" in file_path.parts or file_path.name.startswith("test_")


def is_public_function(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether a function should be considered public API.

    Args:
        node: Function definition to inspect.

    Returns:
        True for non-private functions except test case bodies.
    """

    if node.name.startswith("_"):
        return False
    if node.name in {"main"}:
        return True
    return not node.name.startswith("test_")


def node_line_count(node: ast.AST) -> int:
    """Return the effective line count covered by an AST node.

    Args:
        node: AST node with line metadata.

    Returns:
        Inclusive source line count with docstring-only spans excluded.
    """

    raw_start_lineno = getattr(node, "lineno", None)
    raw_end_lineno = getattr(node, "end_lineno", None) or raw_start_lineno
    start_lineno = raw_start_lineno if isinstance(raw_start_lineno, int) else 1
    end_lineno = raw_end_lineno if isinstance(raw_end_lineno, int) else start_lineno
    covered_lines = set(range(start_lineno, end_lineno + 1))
    covered_lines.difference_update(_docstring_lines(node))
    return max(1, len(covered_lines))


def module_line_count(tree: ast.Module, total_lines: int) -> int:
    """Return effective module lines with docstring-only spans excluded.

    Args:
        tree: Parsed module AST.
        total_lines: Physical source line count.

    Returns:
        Source line count after subtracting module/class/function docstrings.
    """

    covered_lines = set(range(1, total_lines + 1))
    covered_lines.difference_update(_docstring_lines(tree))
    covered_lines.difference_update(_top_level_string_constant_lines(tree))
    return max(1, len(covered_lines))


def _top_level_string_constant_lines(tree: ast.Module) -> set[int]:
    """Return lines for top-level string constants embedded in data tables.

    Args:
        tree: Parsed module AST.

    Returns:
        Source lines occupied by top-level string literals inside assignments.
    """

    constant_lines: set[int] = set()
    for node in tree.body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        for child in ast.walk(node):
            if not (isinstance(child, ast.Constant) and isinstance(child.value, str)):
                continue
            start = getattr(child, "lineno", None)
            end = getattr(child, "end_lineno", start)
            if start is None or end is None:
                continue
            constant_lines.update(range(start, end + 1))
    return constant_lines


def _docstring_lines(node: ast.AST) -> set[int]:
    """Return source lines occupied by docstring expression nodes.

    Args:
        node: AST subtree to inspect.

    Returns:
        Source line numbers containing docstring string literals.
    """

    docstring_lines: set[int] = set()
    for child in ast.walk(node):
        body = getattr(child, "body", None)
        if not isinstance(body, list) or not body:
            continue
        first = body[0]
        if not isinstance(first, ast.Expr):
            continue
        value = first.value
        if not (isinstance(value, ast.Constant) and isinstance(value.value, str)):
            continue
        start = getattr(first, "lineno", None)
        end = getattr(first, "end_lineno", start)
        if start is None or end is None:
            continue
        docstring_lines.update(range(start, end + 1))
    return docstring_lines


def word_count(text: str) -> int:
    """Count meaningful words in docstring text.

    Args:
        text: Text to count.

    Returns:
        Number of non-empty whitespace-separated tokens.
    """

    return len([word for word in text.replace("`", " ").split() if word.strip()])


def class_has_public_fields(node: ast.ClassDef) -> bool:
    """Return whether a typed container has public annotated fields.

    Args:
        node: Class definition to inspect.

    Returns:
        True when a dataclass/model/enum-like class has public fields.
    """

    has_model_base = any(base_name(base) in PUBLIC_CLASS_BASE_NAMES for base in node.bases)
    has_dataclass_decorator = any(decorator_name(decorator) == "dataclass" for decorator in node.decorator_list)
    if not (has_model_base or has_dataclass_decorator):
        return False
    for body_item in node.body:
        if isinstance(body_item, ast.AnnAssign) and isinstance(body_item.target, ast.Name):
            if not body_item.target.id.startswith("_"):
                return True
    return False


def has_attribute_docs(docstring: str) -> bool:
    """Return whether a docstring documents data fields.

    Args:
        docstring: Class docstring text.

    Returns:
        True when Attributes or Fields sections are present.
    """

    normalized = docstring.lower()
    return "attributes:" in normalized or "fields:" in normalized


def has_documentable_parameters(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether a function has public parameters worth documenting.

    Args:
        node: Function definition to inspect.

    Returns:
        True when non-self/non-private arguments are present.
    """

    parameters = [
        *node.args.posonlyargs,
        *node.args.args,
        *node.args.kwonlyargs,
    ]
    return any(argument.arg not in {"self", "cls"} and not argument.arg.startswith("_") for argument in parameters)
