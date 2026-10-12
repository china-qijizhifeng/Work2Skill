"""AST name rendering helpers for quality audit rules."""

from __future__ import annotations

import ast


def base_name(node: ast.AST) -> str:
    """Return the visible name of a base class expression.

    Args:
        node: Base class expression.

    Returns:
        Best-effort class name.
    """

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript):
        return base_name(node.value)
    return ""


def decorator_name(node: ast.AST) -> str:
    """Return the visible name of a decorator expression.

    Args:
        node: Decorator expression.

    Returns:
        Best-effort decorator name.
    """

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Call):
        return decorator_name(node.func)
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def call_name(node: ast.AST) -> str:
    """Return a dotted call target name.

    Args:
        node: Call target expression.

    Returns:
        Best-effort dotted name, or an empty string.
    """

    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = call_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return ""
