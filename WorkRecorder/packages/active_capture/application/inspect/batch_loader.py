"""Backward-compatible imports for active-capture read models."""

from packages.active_capture.application.read_model import RecordingSessionGraph, RecordingSessionGraphReader

RecordingInspectGraph = RecordingSessionGraph
RecordingInspectBatchLoader = RecordingSessionGraphReader

__all__ = ["RecordingInspectBatchLoader", "RecordingInspectGraph"]
