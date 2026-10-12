"""Logging and exception-handler helpers for quality audit rules."""

from __future__ import annotations

import ast
from collections.abc import Sequence

from .ast_names import call_name


def function_has_logging(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether a function body emits structured logging.

    Args:
        node: Function definition to inspect.

    Returns:
        True when logger/logging/log_runtime_event calls are present.
    """

    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            function_name = call_name(child.func)
            if (
                function_name.startswith("logger.")
                or function_name.startswith("logging.")
                or function_name == "log_runtime_event"
            ):
                return True
    return False


def function_has_comment(lines: Sequence[str], node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Return whether a function contains explanatory comments.

    Args:
        lines: Source file lines.
        node: Function definition to inspect.

    Returns:
        True when a source comment appears inside the function body.
    """

    start = max(0, node.lineno - 1)
    end = min(len(lines), getattr(node, "end_lineno", node.lineno))
    return any(line.lstrip().startswith("#") for line in lines[start:end])


def imports_logging(tree: ast.Module) -> bool:
    """Return whether a module imports logging.

    Args:
        tree: Parsed module AST.

    Returns:
        True when ``logging`` is imported directly.
    """

    for node in tree.body:
        if isinstance(node, ast.Import) and any(alias.name == "logging" for alias in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "logging":
            return True
    return False


def defines_logger(tree: ast.Module) -> bool:
    """Return whether a module defines a conventional logger variable.

    Args:
        tree: Parsed module AST.

    Returns:
        True when ``logger`` or ``log`` is assigned at module scope.
    """

    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            if any(name.lower() in {"logger", "log"} for name in names):
                return True
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id.lower() in {"logger", "log"}:
                return True
    return False


def uses_module_logging_emitter(tree: ast.Module) -> bool:
    """Return whether a module calls the top-level logging module.

    Args:
        tree: Parsed module AST.

    Returns:
        True when logging.debug/info/warning/error/etc. is called.
    """

    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            function_name = call_name(node.func)
            if function_name.startswith("logging.") and function_name.split(".")[-1] in {
                "debug",
                "info",
                "warning",
                "error",
                "exception",
                "critical",
                "log",
            }:
                return True
    return False


def is_broad_exception_handler(node: ast.ExceptHandler) -> bool:
    """Return whether an exception handler catches overly broad errors.

    Args:
        node: Exception handler AST node.

    Returns:
        True for bare handlers and Exception/BaseException catches.
    """

    if node.type is None:
        return True
    if isinstance(node.type, ast.Name):
        return node.type.id in {"Exception", "BaseException"}
    return False


def handler_reraises_with_context(node: ast.ExceptHandler) -> bool:
    """Return whether a handler wraps and reraises with context.

    Args:
        node: Exception handler AST node.

    Returns:
        True when a raise statement has an explicit cause.
    """

    for child in ast.walk(node):
        if isinstance(child, ast.Raise) and child.cause is not None:
            return True
    return False


def handler_logs(node: ast.ExceptHandler) -> bool:
    """Return whether an exception handler logs context.

    Args:
        node: Exception handler AST node.

    Returns:
        True when the handler calls a recognized logging function.
    """

    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            function_name = call_name(child.func)
            if (
                function_name.startswith("logger.")
                or function_name.startswith("logging.")
                or function_name == "log_runtime_event"
            ):
                return True
    return False
