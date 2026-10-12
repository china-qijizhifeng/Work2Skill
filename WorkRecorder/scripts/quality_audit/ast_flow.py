"""Return, raise, and label helpers for quality audit rules."""

from __future__ import annotations

import ast
import logging

logger = logging.getLogger(__name__)


def returns_value(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether a function returns a meaningful value.

    Args:
        node: Function definition to inspect.

    Returns:
        True when the signature or body returns something other than ``None``.
    """

    if node.returns is not None and not is_none_annotation(node.returns):
        return True
    for child in ast.walk(node):
        if isinstance(child, ast.Return) and child.value is not None:
            return True
    return False


def raises_exception(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether a function body raises explicitly.

    Args:
        node: Function definition to inspect.

    Returns:
        True when a ``raise`` statement is present.
    """

    return any(isinstance(child, ast.Raise) for child in ast.walk(node))


def has_any_marker(docstring: str, markers: tuple[str, ...]) -> bool:
    """Return whether a normalized docstring contains any marker.

    Args:
        docstring: Lower-cased docstring text.
        markers: Accepted section markers.

    Returns:
        True when one marker appears in the docstring.
    """

    return any(marker in docstring for marker in markers)


def is_none_annotation(annotation: ast.AST) -> bool:
    """Return whether an annotation represents ``None``.

    Args:
        annotation: Annotation AST node.

    Returns:
        True for literal or named ``None`` annotations.
    """

    if isinstance(annotation, ast.Constant):
        return annotation.value is None
    if isinstance(annotation, ast.Name):
        return annotation.id == "None"
    return False


def annotation_label(annotation: ast.AST) -> str:
    """Render an annotation for human-readable findings.

    Args:
        annotation: Annotation AST node.

    Returns:
        Best-effort source representation.
    """

    try:
        return ast.unparse(annotation)
    except Exception:
        logger.debug("Failed to unparse annotation node for audit label.", exc_info=True)
        return annotation.__class__.__name__
