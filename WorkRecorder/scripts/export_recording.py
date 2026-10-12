#!/usr/bin/env python3
"""Export a stored active-capture recording into a browsable directory tree.

The daemon keeps artifacts content-addressed inside an opaque vault and stores
every recording relation in SQLite. This CLI reads that graph and materializes
one folder per recording, with per-keyframe timestamp subfolders holding the
screenshot/OCR/a11y/action evidence plus a trajectory summary.

Examples::

    uv run python scripts/export_recording.py --session-id ses_abc --out ~/recordings
    uv run python scripts/export_recording.py --event-id evt_abc --out ./out
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from packages.active_capture.application.export import RecordingExportError, RecordingExporter
from packages.active_capture.application.read_model import RecordingSessionGraphReader
from packages.artifacts.vault import LocalArtifactVault
from packages.shared.config import WorkRecorderSettings
from packages.storage.container import RepositoryContainer
from packages.storage.database import SQLiteDatabase


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--session-id", help="Recording session id to export.")
    target.add_argument("--event-id", help="Resolve and export the recording owning this event id.")
    parser.add_argument("--out", required=True, type=Path, help="Output root directory.")
    parser.add_argument(
        "--database",
        type=Path,
        default=None,
        help="Override the SQLite database path (defaults to configured database_path).",
    )
    parser.add_argument(
        "--vault-dir",
        type=Path,
        default=None,
        help="Override the artifact vault directory (defaults to configured artifact_vault_dir).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    settings = WorkRecorderSettings()
    database_path = args.database or settings.database_path
    vault_dir = args.vault_dir or settings.artifact_vault_dir

    repositories = RepositoryContainer(SQLiteDatabase(database_path))
    vault = LocalArtifactVault(staging_dir=settings.artifact_staging_dir, vault_dir=vault_dir)
    exporter = RecordingExporter(
        graph_reader=RecordingSessionGraphReader(repository=repositories.active_capture),
        artifacts=repositories.artifacts,
        content_source=vault,
    )

    session_id = args.session_id
    if session_id is None:
        graph = RecordingSessionGraphReader(repository=repositories.active_capture).load_for_event(args.event_id)
        if graph is None:
            print(f"error: no recording found for event {args.event_id}", file=sys.stderr)
            return 1
        session_id = graph.session.session_id

    try:
        result = exporter.export_session(session_id=session_id, output_root=args.out)
    except RecordingExportError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    print(f"exported recording {result.session_id}")
    print(f"  -> {result.output_dir}")
    print(
        f"  keyframes={result.keyframe_dir_count} "
        f"evidence_files={result.evidence_file_count} "
        f"actions={result.action_count} "
        f"video_files={result.video_file_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
