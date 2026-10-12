"""Path-scoped tools for the GUI skill extractor example."""

from __future__ import annotations

import base64
import difflib
import fnmatch
import hashlib
import json
import mimetypes
import re
import shutil
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import yaml

DEFAULT_READ_LINES = 2000
MAX_READ_CHARS = 20_000
MAX_FILE_SIZE_BYTES = 10 * 1024 * 1024
MAX_VIDEO_FRAMES = 20
MAX_BATCH_IMAGES = 20
DEFAULT_GLOB_EXCLUDES = {
    ".eggs",
    ".git",
    ".tox",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
    "venv",
}
SUPPORTED_IMAGE_SUFFIXES = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
SUPPORTED_VIDEO_SUFFIXES = {".avi", ".flv", ".m4v", ".mkv", ".mov", ".mp4", ".webm", ".wmv"}


ToolResult = dict[str, object]


@dataclass(frozen=True)
class ExtractorRoots:
    input_root: Path
    output_root: Path


_roots: ExtractorRoots | None = None
_activity: list[tuple[str, str]] = []
_finalized = False
_provenance: dict[str, object] = {}

RUNTIME_OWNED_OUTPUTS = {
    "extraction-manifest.json",
    "run-events.jsonl",
    "run-metadata.json",
    "run-summary.json",
}
RUNTIME_OWNED_OUTPUT_DIRS = {"trajectory"}


def configure_roots(input_root: str | Path, output_root: str | Path) -> ExtractorRoots:
    """Configure the only filesystem roots visible to extractor tools."""
    global _finalized, _provenance, _roots
    resolved_input = Path(input_root).expanduser().resolve(strict=True)
    if not resolved_input.is_dir():
        raise ValueError(f"Input root is not a directory: {resolved_input}")
    resolved_output = Path(output_root).expanduser().resolve(strict=False)
    resolved_output.mkdir(parents=True, exist_ok=True)
    _roots = ExtractorRoots(input_root=resolved_input, output_root=resolved_output)
    _activity.clear()
    _finalized = False
    _provenance = {}
    return _roots


def configure_provenance(provenance: dict[str, object]) -> None:
    """Attach runtime-owned, credential-free provenance to the final manifest."""
    global _provenance
    _provenance = dict(provenance)


def _configured_roots() -> ExtractorRoots:
    if _roots is None:
        raise RuntimeError("Extractor roots are not configured. Run the extractor through start.py.")
    return _roots


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _resolve_read_path(file_path: str) -> Path:
    roots = _configured_roots()
    raw = Path(file_path).expanduser()
    if raw.is_absolute():
        candidate = raw.resolve(strict=False)
        allowed_roots = (roots.input_root, roots.output_root)
    elif raw.parts and raw.parts[0] == "output":
        candidate = roots.output_root.joinpath(*raw.parts[1:]).resolve(strict=False)
        allowed_roots = (roots.output_root,)
    else:
        candidate = (roots.input_root / raw).resolve(strict=False)
        allowed_roots = (roots.input_root,)
    if not any(_is_within(candidate, root) for root in allowed_roots):
        raise PermissionError(f"Path is outside the extractor read roots: {file_path}")
    return candidate


def _resolve_output_path(file_path: str) -> Path:
    roots = _configured_roots()
    raw = Path(file_path).expanduser()
    if raw.parts and raw.parts[0] == "output":
        raw = Path(*raw.parts[1:])
    candidate = raw.resolve(strict=False) if raw.is_absolute() else (roots.output_root / raw).resolve(strict=False)
    if not _is_within(candidate, roots.output_root):
        raise PermissionError(f"Path is outside the extractor output root: {file_path}")
    return candidate


def _error(message: str, error_type: str) -> ToolResult:
    return {
        "status": "error",
        "content": message,
        "returnDisplay": message,
        "error": {"message": message, "type": error_type},
    }


def _record_activity(tool_name: str, logical_path: str) -> None:
    _activity.append((tool_name, logical_path))


def extraction_is_finalized() -> bool:
    """Return whether ``finalize_extraction`` passed for the configured run."""
    return _finalized


def require_finalized_extraction() -> None:
    """Raise when the agent returned without passing the finalization gate."""
    if not _finalized:
        raise RuntimeError(
            "The agent stopped without successfully calling finalize_extraction. "
            "The extraction is incomplete."
        )


def _logical_path(path: Path) -> str:
    roots = _configured_roots()
    if _is_within(path, roots.output_root):
        relative = path.relative_to(roots.output_root).as_posix()
        return "output" if relative == "." else f"output/{relative}"
    relative = path.relative_to(roots.input_root).as_posix()
    return "." if relative == "." else relative


def _load_ignore_patterns(directory: Path) -> list[str]:
    gitignore = directory / ".gitignore"
    if not gitignore.is_file():
        return []
    return [
        line.rstrip("/")
        for raw_line in gitignore.read_text(encoding="utf-8", errors="replace").splitlines()
        if (line := raw_line.strip()) and not line.startswith("#")
    ]


def _matches_any_pattern(path: str, patterns: list[str]) -> bool:
    name = Path(path).name
    parts = Path(path).parts
    return any(
        fnmatch.fnmatch(path, pattern)
        or fnmatch.fnmatch(name, pattern)
        or any(fnmatch.fnmatch(part, pattern) for part in parts)
        for pattern in patterns
    )


def list_directory(
    dir_path: str,
    ignore: list[str] | None = None,
    file_filtering_options: dict[str, bool] | None = None,
    show_hidden: bool = True,
) -> ToolResult:
    """Scoped adapter for NexAU's built-in ``list_directory`` contract."""
    try:
        path = _resolve_read_path(dir_path)
        if not path.exists():
            return _error(f"Error: Directory not found or inaccessible: {dir_path}", "FILE_NOT_FOUND")
        if not path.is_dir():
            return _error(f"Error: Path is not a directory: {dir_path}", "PATH_IS_NOT_A_DIRECTORY")
        ignore_patterns = list(ignore or [])
        if (file_filtering_options or {}).get("respect_git_ignore", True):
            ignore_patterns.extend(_load_ignore_patterns(path))
        entries = [
            item
            for item in path.iterdir()
            if (show_hidden or not item.name.startswith(".")) and not _matches_any_pattern(item.name, ignore_patterns)
        ]
        entries.sort(key=lambda item: (not item.is_dir(), item.name.lower()))
        if not entries:
            return {
                "content": f"Directory {_logical_path(path)} is empty.",
                "returnDisplay": "Directory is empty.",
            }
        lines = [f"{'[DIR] ' if item.is_dir() else ''}{item.name}" for item in entries]
        ignored_count = len(list(path.iterdir())) - len(entries)
        content = f"Directory listing for {_logical_path(path)}:\n" + "\n".join(lines)
        display = f"Listed {len(entries)} item(s)."
        if ignored_count:
            content += f"\n\n({ignored_count} ignored)"
            display += f" ({ignored_count} ignored)"
        return {"content": content, "returnDisplay": display}
    except PermissionError as exc:
        return _error(f"Permission denied: {exc}", "PERMISSION_DENIED")
    except (OSError, RuntimeError) as exc:
        return _error(f"Error listing directory: {exc}", "LS_EXECUTION_ERROR")


def _glob_matches(relative_path: str, pattern: str, case_sensitive: bool) -> bool:
    candidate = relative_path if case_sensitive else relative_path.lower()
    effective_pattern = pattern if case_sensitive else pattern.lower()
    if "/" not in effective_pattern:
        return fnmatch.fnmatch(Path(candidate).name, effective_pattern)
    if fnmatch.fnmatch(candidate, effective_pattern):
        return True
    return effective_pattern.startswith("**/") and fnmatch.fnmatch(candidate, effective_pattern[3:])


def glob(
    pattern: str,
    dir_path: str | None = None,
    case_sensitive: bool = False,
    respect_git_ignore: bool = True,
) -> ToolResult:
    """Scoped adapter for NexAU's built-in ``glob`` contract."""
    try:
        if not pattern.strip():
            return _error("The 'pattern' parameter cannot be empty.", "INVALID_PATTERN")
        search_dir = _resolve_read_path(dir_path or ".")
        if not search_dir.exists():
            return _error(f"Search path does not exist: {dir_path}", "DIRECTORY_NOT_FOUND")
        if not search_dir.is_dir():
            return _error(f"Search path is not a directory: {dir_path}", "NOT_A_DIRECTORY")
        ignore_patterns = list(DEFAULT_GLOB_EXCLUDES)
        if respect_git_ignore:
            ignore_patterns.extend(_load_ignore_patterns(search_dir))
        matches: list[Path] = []
        for candidate in search_dir.rglob("*"):
            relative = candidate.relative_to(search_dir).as_posix()
            if _matches_any_pattern(relative, ignore_patterns):
                continue
            if _glob_matches(relative, pattern, case_sensitive):
                matches.append(candidate)
        matches.sort(key=lambda item: (item.stat().st_mtime, item.as_posix()), reverse=True)
        rendered = [_logical_path(match) for match in matches]
        logical_dir = _logical_path(search_dir)
        if not rendered:
            return {
                "content": f'No files found matching pattern "{pattern}" within {logical_dir}',
                "returnDisplay": "No files found",
            }
        content = (
            f'Found {len(rendered)} match(es) for "{pattern}" within {logical_dir}, '
            "sorted by modification time (newest first):\n"
            + "\n".join(rendered)
        )
        return {"content": content, "returnDisplay": f"Found {len(rendered)} matching file(s)"}
    except PermissionError as exc:
        return _error(f"Permission denied: {exc}", "PERMISSION_DENIED")
    except (OSError, RuntimeError) as exc:
        return _error(f"Error during glob search operation: {exc}", "GLOB_EXECUTION_ERROR")


def read_file(file_path: str, offset: int | None = None, limit: int | None = None) -> ToolResult:
    """Scoped adapter for NexAU's built-in ``read_file`` contract."""
    try:
        path = _resolve_read_path(file_path)
        if not path.exists():
            return _error(f"File not found: {file_path}", "FILE_NOT_FOUND")
        if path.is_dir():
            return _error(f"Path is a directory, not a file: {file_path}", "PATH_IS_DIRECTORY")
        if path.suffix.lower() in SUPPORTED_IMAGE_SUFFIXES:
            return _error(
                f"File '{file_path}' is an image file ({path.suffix.lower()}) — Not supported; "
                "use read_visual_evidence.",
                "DO_NOT_SUPPORT_VISUAL",
            )
        if path.suffix.lower() in SUPPORTED_VIDEO_SUFFIXES:
            return _error(
                f"File '{file_path}' is a video file ({path.suffix.lower()}) — Not supported; "
                "use get_video_metadata before watch_video or extract_video_frames.",
                "DO_NOT_SUPPORT_VISUAL",
            )
        if path.stat().st_size > MAX_FILE_SIZE_BYTES:
            return _error(
                f"File too large ({path.stat().st_size} bytes). Maximum size is {MAX_FILE_SIZE_BYTES} bytes.",
                "FILE_TOO_LARGE",
            )
        start = int(offset) if offset is not None and offset >= 0 else 0
        line_limit = int(limit) if limit is not None and limit > 0 else DEFAULT_READ_LINES
        text = path.read_bytes().decode("utf-8", errors="replace")
        lines = text.splitlines()
        selected = lines[start : start + line_limit]
        rendered: list[str] = []
        char_count = 0
        for index, line in enumerate(selected, start=start + 1):
            shortened = line[:2000] + "... [truncated]" if len(line) > 2000 else line
            numbered = f"{index}| {shortened}"
            if rendered and char_count + len(numbered) + 1 > MAX_READ_CHARS:
                break
            rendered.append(numbered[:MAX_READ_CHARS] if not rendered else numbered)
            char_count += len(rendered[-1]) + 1
        next_offset = start + len(rendered)
        footer = f"\n\nLines {start + 1}-{next_offset} of {len(lines)}."
        if next_offset < len(lines):
            footer += f" Continue with offset={next_offset}."
        result: ToolResult = {
            "content": "\n".join(rendered) + footer,
            "returnDisplay": f"Read {len(rendered)} line(s).",
        }
        _record_activity("read_file", _logical_path(path))
        return result
    except PermissionError as exc:
        return _error(f"Permission denied: {exc}", "PERMISSION_DENIED")
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _error(f"Error reading file: {exc}", "READ_ERROR")


def _image_block(path: Path, label: str, detail: str = "high") -> dict[str, str]:
    mime_type = mimetypes.guess_type(path.name)[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return {
        "type": "image",
        "image_url": f"data:{mime_type};base64,{encoded}",
        "detail": detail,
        "label": label,
    }


def _resized_image_block(path: Path, detail: str, image_max_size: int | None) -> dict[str, str]:
    if image_max_size is None:
        return _image_block(path, path.name, detail)
    width = int(image_max_size)
    if width <= 0:
        raise ValueError("image_max_size must be a positive integer.")
    command = [
        _media_binary("ffmpeg"),
        "-v",
        "error",
        "-i",
        str(path),
        "-vf",
        f"scale='min({width},iw)':-2",
        "-frames:v",
        "1",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "pipe:1",
    ]
    result = _run_media_command(command, timeout=30)
    if result.returncode != 0 or not result.stdout:
        raise RuntimeError(result.stderr.decode(errors="replace")[:500] or "Failed to resize image.")
    return {
        "type": "image",
        "image_url": f"data:image/jpeg;base64,{base64.b64encode(result.stdout).decode('ascii')}",
        "detail": detail,
        "label": path.name,
    }


def read_visual_evidence(
    file_paths: object,
    image_detail: str | None = None,
    image_max_size: int | None = None,
) -> dict[str, object]:
    """Read 1–20 scoped images as one path-labeled multimodal result."""
    try:
        if not isinstance(file_paths, list):
            return _error("file_paths must be a list of image path strings.", "INVALID_PARAMETER")
        raw_paths = cast(list[object], file_paths)
        if any(not isinstance(path, str) for path in raw_paths):
            return _error("file_paths must be a list of image path strings.", "INVALID_PARAMETER")
        paths = cast(list[str], raw_paths)
        if not paths:
            return _error("file_paths must contain at least one image path.", "INVALID_PARAMETER")
        if len(paths) > MAX_BATCH_IMAGES:
            return _error(
                f"At most {MAX_BATCH_IMAGES} images may be read in one call.",
                "INVALID_PARAMETER",
            )
        if len(set(paths)) != len(paths):
            return _error("file_paths must not contain duplicates.", "INVALID_PARAMETER")
        detail = image_detail or "auto"
        if detail not in {"auto", "high", "low"}:
            return _error(f"Invalid image_detail value: {detail!r}.", "INVALID_PARAMETER")

        resolved: list[tuple[str, Path]] = []
        for file_path in paths:
            path = _resolve_read_path(file_path)
            if not path.exists():
                return _error(f"File not found: {file_path}", "FILE_NOT_FOUND")
            if path.is_dir():
                return _error(f"Path is a directory, not a file: {file_path}", "PATH_IS_DIRECTORY")
            if path.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
                return _error(f"Unsupported image file: {file_path}", "NOT_IMAGE_FILE")
            if path.stat().st_size > MAX_FILE_SIZE_BYTES:
                return _error(
                    f"Image file too large ({path.stat().st_size} bytes): {file_path}. "
                    f"Maximum size is {MAX_FILE_SIZE_BYTES} bytes.",
                    "FILE_TOO_LARGE",
                )
            resolved.append((file_path, path))

        content: list[dict[str, str]] = []
        for index, (_, path) in enumerate(resolved, start=1):
            logical_path = _logical_path(path)
            content.append(
                {
                    "type": "text",
                    "text": f"Image {index}/{len(resolved)}: {logical_path}",
                }
            )
            content.append(_resized_image_block(path, detail, image_max_size))
            _record_activity("read_visual_evidence", _logical_path(path))
        return {
            "content": content,
            "returnDisplay": f"Read {len(resolved)} image file(s).",
        }
    except PermissionError as exc:
        return _error(f"Permission denied: {exc}", "PERMISSION_DENIED")
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return _error(f"Error reading visual files: {exc}", "VISUAL_READ_ERROR")


def read_image(file_path: str, detail: str = "high") -> dict[str, object]:
    """Backward-compatible Python helper; the registered tool is read_visual_evidence."""
    return read_visual_evidence(file_paths=[file_path], image_detail=detail)


def _media_binary(name: str) -> str:
    binary = shutil.which(name)
    if binary is None:
        raise RuntimeError(f"{name} is required for video analysis but is not installed or not on PATH.")
    return binary


def _run_media_command(command: list[str], timeout: int = 60) -> subprocess.CompletedProcess[bytes]:
    return subprocess.run(command, capture_output=True, check=False, timeout=timeout)


def _video_path(file_path: str) -> Path:
    path = _resolve_read_path(file_path)
    if not path.is_file() or path.suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES:
        raise ValueError(f"Unsupported video file: {file_path}")
    return path


def get_video_metadata(file_path: str) -> ToolResult:
    """Return duration, dimensions, frame rate, and codec for a video."""
    try:
        path = _video_path(file_path)
        command = [
            _media_binary("ffprobe"),
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=codec_name,width,height,r_frame_rate,duration:format=duration,size",
            "-of",
            "json",
            str(path),
        ]
        result = _run_media_command(command, timeout=30)
        if result.returncode != 0:
            return _error(result.stderr.decode(errors="replace")[:1000], "FFPROBE_ERROR")
        payload = json.loads(result.stdout.decode("utf-8"))
        _record_activity("get_video_metadata", _logical_path(path))
        return {"content": json.dumps(payload, indent=2), "returnDisplay": "Read video metadata."}
    except (OSError, ValueError, PermissionError, RuntimeError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        return _error(str(exc), "VIDEO_METADATA_ERROR")


def _validate_timestamps(timestamps_ms: list[int]) -> list[int]:
    if not timestamps_ms:
        raise ValueError("At least one timestamp is required.")
    if len(timestamps_ms) > MAX_VIDEO_FRAMES:
        raise ValueError(f"At most {MAX_VIDEO_FRAMES} frames may be requested at once.")
    normalized = [int(timestamp) for timestamp in timestamps_ms]
    if any(timestamp < 0 for timestamp in normalized):
        raise ValueError("Video timestamps must be non-negative.")
    return normalized


def _video_duration_ms(path: Path) -> int:
    command = [
        _media_binary("ffprobe"),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    result = _run_media_command(command, timeout=30)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.decode(errors="replace")[:500])
    return max(0, int(float(result.stdout.decode("utf-8").strip()) * 1000))


def _extract_frames(path: Path, timestamps_ms: list[int], frame_width: int | None) -> list[dict[str, str]]:
    ffmpeg = _media_binary("ffmpeg")
    if frame_width is not None and (frame_width < 64 or frame_width > 4096):
        raise ValueError("frame_width must be between 64 and 4096 pixels.")
    # Container duration is an exclusive upper bound and can be slightly later
    # than the final decodable frame. Keep a small margin and retry backwards.
    safe_last_ms = max(0, _video_duration_ms(path) - 100)
    blocks: list[dict[str, str]] = []
    for requested_ms in _validate_timestamps(timestamps_ms):
        initial_ms = min(requested_ms, safe_last_ms)
        candidates = list(dict.fromkeys(max(0, initial_ms - backoff) for backoff in (0, 100, 250, 500, 1000)))
        result: subprocess.CompletedProcess[bytes] | None = None
        actual_ms = initial_ms
        for candidate_ms in candidates:
            command = [ffmpeg, "-v", "error", "-ss", f"{candidate_ms / 1000:.3f}", "-i", str(path), "-frames:v", "1"]
            if frame_width is not None:
                command.extend(["-vf", f"scale={frame_width}:-2"])
            command.extend(["-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1"])
            result = _run_media_command(command)
            if result.returncode == 0 and result.stdout:
                actual_ms = candidate_ms
                break
        if result is None or result.returncode != 0 or not result.stdout:
            diagnostics = "" if result is None else result.stderr.decode(errors="replace")[:500]
            raise RuntimeError(f"Failed to extract frame at or before {requested_ms}ms: {diagnostics}")
        encoded = base64.b64encode(result.stdout).decode("ascii")
        label = f"Video frame at {actual_ms}ms ({actual_ms / 1000:.3f}s)"
        if actual_ms != requested_ms:
            label += f"; adjusted from requested {requested_ms}ms"
        blocks.append(
            {
                "type": "image",
                "image_url": f"data:image/jpeg;base64,{encoded}",
                "detail": "high",
                "label": label,
            }
        )
    return blocks


def extract_video_frames(file_path: str, timestamps_ms: list[int], frame_width: int | None = None) -> dict[str, object]:
    """Extract full-detail video frames at exact millisecond timestamps."""
    try:
        path = _video_path(file_path)
        blocks = _extract_frames(path, timestamps_ms, frame_width)
        _record_activity("extract_video_frames", _logical_path(path))
        return {"content": blocks, "returnDisplay": f"Extracted {len(blocks)} frame(s)."}
    except (OSError, ValueError, PermissionError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return _error(str(exc), "VIDEO_FRAME_ERROR")


def watch_video(
    file_path: str,
    start_ms: int = 0,
    end_ms: int | None = None,
    interval_ms: int = 5000,
    max_frames: int = 12,
    frame_width: int | None = 1280,
) -> dict[str, object]:
    """Watch a video segment by returning evenly spaced timestamped frames."""
    try:
        if start_ms < 0:
            raise ValueError("start_ms must be non-negative.")
        if interval_ms < 100:
            raise ValueError("interval_ms must be at least 100ms.")
        if max_frames <= 0 or max_frames > MAX_VIDEO_FRAMES:
            raise ValueError(f"max_frames must be between 1 and {MAX_VIDEO_FRAMES}.")
        if end_ms is not None and end_ms <= start_ms:
            raise ValueError("end_ms must be greater than start_ms.")
        timestamps: list[int] = []
        timestamp = start_ms
        while len(timestamps) < max_frames and (end_ms is None or timestamp <= end_ms):
            timestamps.append(timestamp)
            timestamp += interval_ms
        path = _video_path(file_path)
        blocks = _extract_frames(path, timestamps, frame_width)
        _record_activity("watch_video", _logical_path(path))
        return {"content": blocks, "returnDisplay": f"Watched {len(blocks)} sampled frame(s)."}
    except (OSError, ValueError, PermissionError, RuntimeError, subprocess.TimeoutExpired) as exc:
        return _error(str(exc), "WATCH_VIDEO_ERROR")


def write_file(file_path: str, content: str) -> ToolResult:
    """Scoped adapter for NexAU's built-in ``write_file`` contract."""
    try:
        if not file_path.strip():
            return _error('Missing or empty "file_path"', "INVALID_FILE_PATH")
        path = _resolve_output_path(file_path)
        relative = path.relative_to(_configured_roots().output_root).as_posix()
        if relative in RUNTIME_OWNED_OUTPUTS or Path(relative).parts[0] in RUNTIME_OWNED_OUTPUT_DIRS:
            return _error(
                f"Output file is owned by the extraction runtime and cannot be written: output/{relative}",
                "RUNTIME_FILE_RESERVED",
            )
        if path.exists() and path.is_dir():
            return _error(f"Path is a directory, not a file: {file_path}", "TARGET_IS_DIRECTORY")
        is_new_file = not path.exists()
        original_content = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _record_activity("write_file", f"output/{relative}")
        diff = "".join(
            difflib.unified_diff(
                original_content.splitlines(keepends=True),
                content.splitlines(keepends=True),
                fromfile=str(path),
                tofile=str(path),
            )
        )
        original_lines = set(original_content.splitlines())
        new_lines = set(content.splitlines())
        message = (
            f"Successfully created and wrote to new file: output/{relative}."
            if is_new_file
            else f"Successfully overwrote file: output/{relative}."
        )
        return {
            "content": message,
            "returnDisplay": {
                "fileDiff": diff,
                "fileName": path.name,
                "filePath": f"output/{relative}",
                "originalContent": original_content,
                "newContent": content,
                "diffStat": {
                    "added": len(new_lines - original_lines),
                    "removed": len(original_lines - new_lines),
                },
                "isNewFile": is_new_file,
            },
        }
    except PermissionError as exc:
        return _error(f"Permission denied writing to file: {exc}", "PERMISSION_DENIED")
    except (OSError, RuntimeError) as exc:
        return _error(f"Error writing to file '{file_path}': {exc}", "FILE_WRITE_FAILURE")


def _frontmatter(content: str) -> tuple[dict[str, object], str]:
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", content, re.DOTALL)
    if match is None:
        raise ValueError("SKILL.md must start with YAML frontmatter enclosed by --- markers.")
    loaded: object = yaml.safe_load(match.group(1))
    if not isinstance(loaded, dict):
        raise ValueError("SKILL.md frontmatter must be a YAML mapping.")
    metadata = {str(key): value for key, value in cast(dict[object, object], loaded).items()}
    return metadata, match.group(2).strip()


def _validate_skill(skill_path: str) -> ToolResult:
    try:
        folder = _resolve_output_path(skill_path)
        skill_file = folder / "SKILL.md"
        if not skill_file.is_file():
            return _error(f"SKILL.md not found under output/{skill_path}", "SKILL_NOT_FOUND")
        content = skill_file.read_text(encoding="utf-8-sig")
        metadata, body = _frontmatter(content)
        errors: list[str] = []
        warnings: list[str] = []
        name = metadata.get("name")
        description = metadata.get("description")
        if not isinstance(name, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name):
            errors.append("name must use lowercase hyphen-case")
        if not isinstance(description, str) or not description.strip():
            errors.append("description must be a non-empty string")
        if not body:
            errors.append("skill body must not be empty")
        if name and folder.name != name:
            errors.append(f"folder name '{folder.name}' must match skill name '{name}'")
        if re.search(r"\b(?:x|y)\s*[=:]\s*\d{2,4}\b|\(\s*\d{2,4}\s*,\s*\d{2,4}\s*\)", body, re.IGNORECASE):
            warnings.append("body appears to contain fixed screen coordinates")
        if re.search(r"(?:/root/|/Users/|\\Users\\|benchmark/[^\s]+)", body):
            warnings.append("body appears to contain a machine- or episode-specific path")
        if re.search(r"\b\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?\b", body):
            warnings.append("body contains timestamps; verify they are not trajectory-specific")
        status = "valid" if not errors else "invalid"
        payload = {"status": status, "errors": errors, "warnings": warnings}
        result: ToolResult = {
            "content": json.dumps(payload, indent=2),
            "returnDisplay": f"Skill validation {status} with {len(warnings)} warning(s).",
        }
        if errors:
            result["error"] = {"message": "; ".join(errors), "type": "INVALID_SKILL"}
        return result
    except (OSError, PermissionError, RuntimeError, ValueError, yaml.YAMLError) as exc:
        return _error(str(exc), "SKILL_VALIDATION_ERROR")


def validate_skill(skill_path: str) -> ToolResult:
    """Internal API used by tests and finalization; not registered as an agent tool."""
    return _validate_skill(skill_path)


def _activity_index(tool_name: str, logical_path: str, *, last: bool = False) -> int | None:
    indexes = [
        index
        for index, (activity_tool, activity_path) in enumerate(_activity)
        if activity_tool == tool_name and activity_path == logical_path
    ]
    if not indexes:
        return None
    return indexes[-1] if last else indexes[0]


def finalize_extraction(_call: str | None = None) -> ToolResult:
    """Validate final Skills, atomically write runtime metadata, and stop.

    ``_call`` is an optional, ignored compatibility note.  Some Anthropic
    models attach a short completion rationale to otherwise parameterless
    tool calls.  The tool schema still exposes no parameters; only the
    Opus-specific schema opts into this field.
    """
    global _finalized

    roots = _configured_roots()
    _finalized = False
    errors: list[str] = []
    skill_files = sorted(roots.output_root.glob("*/SKILL.md"))
    if not skill_files:
        errors.append("at least one <skill-name>/SKILL.md is required")
    task_reads = sorted(
        {
            path
            for tool_name, path in _activity
            if tool_name == "read_file"
            and not path.startswith("output/")
            and Path(path).name == "task.json"
        }
    )
    if not task_reads:
        errors.append("the authoritative task.json must be read with read_file before finalization")

    generated_skills: list[dict[str, object]] = []
    validation_results: list[dict[str, object]] = []
    for skill_file in skill_files:
        relative_skill_file = skill_file.relative_to(roots.output_root).as_posix()
        logical_skill_file = f"output/{relative_skill_file}"
        logical_skill_dir = logical_skill_file.removesuffix("/SKILL.md")
        validation = _validate_skill(logical_skill_dir)
        if "error" in validation:
            errors.append(f"{logical_skill_file} failed validation: {validation['content']}")
        related_writes = [
            index
            for index, (tool_name, path) in enumerate(_activity)
            if tool_name == "write_file" and path == logical_skill_file
        ]
        read_index = _activity_index("read_file", logical_skill_file, last=True)
        if not related_writes:
            errors.append(f"{logical_skill_file} was not created through write_file")
        elif read_index is None or read_index < related_writes[-1]:
            errors.append(f"{logical_skill_file} must be read with read_file after its final write")

        if "error" not in validation:
            content = skill_file.read_text(encoding="utf-8-sig")
            metadata, _ = _frontmatter(content)
            validation_payload = json.loads(cast(str, validation["content"]))
            warnings = validation_payload.get("warnings", []) if isinstance(validation_payload, dict) else []
            entry = {
                "name": cast(str, metadata["name"]),
                "description": cast(str, metadata["description"]),
                "path": relative_skill_file,
                "sha256": hashlib.sha256(skill_file.read_bytes()).hexdigest(),
            }
            generated_skills.append(entry)
            validation_results.append(
                {
                    "name": entry["name"],
                    "path": relative_skill_file,
                    "status": "valid",
                    "warnings": warnings,
                }
            )

    for index, (tool_name, path) in enumerate(_activity):
        if tool_name not in {"watch_video", "extract_video_frames"}:
            continue
        if Path(path).suffix.lower() not in SUPPORTED_VIDEO_SUFFIXES:
            continue
        if not any(
            prior_tool == "get_video_metadata" and prior_path == path
            for prior_tool, prior_path in _activity[:index]
        ):
            errors.append(f"get_video_metadata must be called before video sampling: {path}")

    inspected_sources = sorted(
        {
            path
            for tool_name, path in _activity
            if tool_name
            in {
                "read_file",
                "read_visual_evidence",
                "get_video_metadata",
                "watch_video",
                "extract_video_frames",
            }
            and path != "output"
            and not path.startswith("output/")
        }
    )
    if errors:
        message = "Extraction is not ready to finalize:\n- " + "\n- ".join(errors)
        return _error(message, "EXTRACTION_NOT_READY")

    skill_set_material = "\n".join(
        f"{entry['path']}:{entry['sha256']}" for entry in generated_skills
    ).encode("utf-8")
    manifest = {
        "schema_version": "1.0",
        "generated_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "generated_by": "finalize_extraction",
        "task_paths": task_reads,
        "inspected_sources": inspected_sources,
        "generated_skills": generated_skills,
        "skill_set_sha256": hashlib.sha256(skill_set_material).hexdigest(),
        "validation_results": validation_results,
        "provenance": _provenance,
    }
    manifest_path = roots.output_root / "extraction-manifest.json"
    temporary_manifest_path = roots.output_root / ".extraction-manifest.json.tmp"
    try:
        temporary_manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary_manifest_path.replace(manifest_path)
    except OSError as exc:
        return _error(f"Failed to write final runtime metadata: {exc}", "FINALIZATION_WRITE_FAILURE")

    _finalized = True
    return {
        "result": (
            f"Extraction finalized successfully with {len(skill_files)} validated skill(s), "
            f"{len(inspected_sources)} inspected source(s), and a runtime-owned manifest."
        )
    }
