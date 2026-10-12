"""Annotation helpers for quality audit rules."""

from __future__ import annotations

import ast
from collections.abc import Iterable

from .ast_names import base_name, decorator_name
from .constants import BARE_COLLECTION_ANNOTATIONS, TYPED_MODEL_BASE_NAMES


def function_arguments(node: ast.FunctionDef | ast.AsyncFunctionDef) -> tuple[ast.arg, ...]:
    """Return all named function parameters except varargs containers.

    Args:
        node: Function definition to inspect.

    Returns:
        Positional-only, positional, and keyword-only argument nodes.
    """

    return (
        *node.args.posonlyargs,
        *node.args.args,
        *node.args.kwonlyargs,
    )


def iter_node_annotations(node: ast.AST) -> Iterable[tuple[ast.AST, int]]:
    """Yield annotations attached to a supported AST node.

    Args:
        node: AST node that may carry a type annotation.

    Returns:
        Tuples of annotation node and source line.
    """

    if isinstance(node, ast.AnnAssign):
        yield node.annotation, node.lineno
    if isinstance(node, ast.arg) and node.annotation is not None:
        yield node.annotation, node.lineno
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.returns is not None:
        yield node.returns, node.lineno


def is_typed_data_class(node: ast.ClassDef) -> bool:
    """Return whether a class is a typed data/model container.

    Args:
        node: Class definition to inspect.

    Returns:
        True for dataclasses and Pydantic-style BaseModel containers.
    """

    has_model_base = any(base_name(base) in TYPED_MODEL_BASE_NAMES for base in node.bases)
    has_dataclass_decorator = any(decorator_name(decorator) == "dataclass" for decorator in node.decorator_list)
    return has_model_base or has_dataclass_decorator


def annotation_contains_any(annotation: ast.AST) -> bool:
    """Return whether an annotation contains an ``Any`` marker.

    Args:
        annotation: Annotation AST node to inspect.

    Returns:
        True when the annotation or one of its children references ``Any``.
    """

    if isinstance(annotation, ast.Name):
        return annotation.id == "Any"
    if isinstance(annotation, ast.Attribute):
        return annotation.attr == "Any"
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        return string_annotation_has_name(annotation.value, "Any")
    return any(annotation_contains_any(child) for child in ast.iter_child_nodes(annotation))


def annotation_is_bare_collection(annotation: ast.AST) -> bool:
    """Return whether an annotation is a bare collection type.

    Args:
        annotation: Annotation AST node to inspect.

    Returns:
        True for unspecialized collection annotations such as ``list``.
    """

    if isinstance(annotation, ast.Name):
        return annotation.id in BARE_COLLECTION_ANNOTATIONS
    if isinstance(annotation, ast.Attribute):
        return annotation.attr in BARE_COLLECTION_ANNOTATIONS
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        stripped = annotation.value.strip().strip("'\"")
        return stripped in BARE_COLLECTION_ANNOTATIONS
    return False


def annotation_is_dict_any(annotation: ast.AST) -> bool:
    """Return whether an annotation exposes a ``dict[..., Any]`` boundary.

    Args:
        annotation: Annotation AST node to inspect.

    Returns:
        True for dict annotations whose value side contains ``Any``.
    """

    if isinstance(annotation, ast.Subscript):
        if annotation_root_name(annotation.value) not in {"dict", "Dict"}:
            return any(annotation_is_dict_any(child) for child in ast.iter_child_nodes(annotation))
        return annotation_contains_any(annotation.slice)
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        normalized = annotation.value.replace(" ", "")
        return any(
            marker in normalized
            for marker in (
                "dict[str,Any]",
                "Dict[str,Any]",
                "typing.Dict[str,Any]",
            )
        )
    return any(annotation_is_dict_any(child) for child in ast.iter_child_nodes(annotation))


def annotation_root_name(annotation: ast.AST) -> str:
    """Return the root symbol for an annotation expression.

    Args:
        annotation: Annotation AST node.

    Returns:
        Root name or attribute string when available.
    """

    if isinstance(annotation, ast.Name):
        return annotation.id
    if isinstance(annotation, ast.Attribute):
        return annotation.attr
    if isinstance(annotation, ast.Subscript):
        return annotation_root_name(annotation.value)
    return ""


def string_annotation_has_name(annotation: str, name: str) -> bool:
    """Return whether a stringified annotation contains a symbol name.

    Args:
        annotation: String annotation body.
        name: Symbol name to search for.

    Returns:
        True when the symbol appears as a separated token.
    """

    padded = f" {annotation.replace('.', ' ').replace('[', ' ').replace(']', ' ').replace(',', ' ')} "
    return f" {name} " in padded
