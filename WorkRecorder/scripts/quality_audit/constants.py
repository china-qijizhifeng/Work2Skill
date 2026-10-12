"""Constants used by the WorkRecorder repository quality audit."""

DEFAULT_PATHS = (
    "scripts",
    "apps",
    "packages",
    "services",
    "tests",
)
DEFAULT_MAX_FILE_LINES_WARNING = 700
DEFAULT_MAX_FILE_LINES_VIOLATION = 700
DEFAULT_MAX_CLASS_LINES_WARNING = 500
DEFAULT_MAX_FUNCTION_LINES_WARNING = 100
DEFAULT_MAX_TOP_LEVEL_FUNCTIONS_WARNING = 8
DEFAULT_MAX_TOP_LEVEL_FUNCTIONS_VIOLATION = 40
DEFAULT_MIN_DOCSTRING_WORDS = 4
DEFAULT_TOP_LONG_FILES = 15
DEFAULT_MAX_FINDINGS = 200
DEFAULT_EXCLUDED_DIRS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "logs",
    "node_modules",
    "reference_code",
    "site",
    "test-logs",
}
PUBLIC_CLASS_BASE_NAMES = {"BaseModel", "Enum", "StrEnum", "IntEnum"}
TYPED_MODEL_BASE_NAMES = {"BaseModel"}
BARE_COLLECTION_ANNOTATIONS = {
    "Callable",
    "Collection",
    "Dict",
    "FrozenSet",
    "Iterable",
    "Iterator",
    "List",
    "Mapping",
    "MutableMapping",
    "Sequence",
    "Set",
    "Tuple",
    "dict",
    "frozenset",
    "list",
    "set",
    "tuple",
}
