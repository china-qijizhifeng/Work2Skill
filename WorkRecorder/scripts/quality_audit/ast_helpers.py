"""Compatibility exports for repository quality audit AST helpers."""

from __future__ import annotations

from .ast_annotations import (
    annotation_contains_any,
    annotation_is_bare_collection,
    annotation_is_dict_any,
    annotation_root_name,
    function_arguments,
    is_typed_data_class,
    iter_node_annotations,
    string_annotation_has_name,
)
from .ast_docstrings import (
    class_has_public_fields,
    has_attribute_docs,
    has_documentable_parameters,
    is_public_function,
    is_test_path,
    module_line_count,
    node_line_count,
    word_count,
)
from .ast_flow import annotation_label, has_any_marker, is_none_annotation, raises_exception, returns_value
from .ast_logging import (
    defines_logger,
    function_has_comment,
    function_has_logging,
    handler_logs,
    handler_reraises_with_context,
    imports_logging,
    is_broad_exception_handler,
    uses_module_logging_emitter,
)
from .ast_names import base_name, call_name, decorator_name

__all__ = [
    "annotation_contains_any",
    "annotation_is_bare_collection",
    "annotation_is_dict_any",
    "annotation_label",
    "annotation_root_name",
    "base_name",
    "call_name",
    "class_has_public_fields",
    "decorator_name",
    "defines_logger",
    "function_arguments",
    "function_has_comment",
    "function_has_logging",
    "handler_logs",
    "handler_reraises_with_context",
    "has_any_marker",
    "has_attribute_docs",
    "has_documentable_parameters",
    "imports_logging",
    "is_broad_exception_handler",
    "is_none_annotation",
    "is_public_function",
    "is_test_path",
    "is_typed_data_class",
    "iter_node_annotations",
    "module_line_count",
    "node_line_count",
    "raises_exception",
    "returns_value",
    "string_annotation_has_name",
    "uses_module_logging_emitter",
    "word_count",
]
