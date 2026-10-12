"""Configuration loading for the local WorkRecorder runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class WorkRecorderSettings(BaseSettings):
    """Typed local runtime settings loaded from environment variables.

    Attributes:
        database_path: SQLite database path used by the daemon.
        artifact_staging_dir: Directory where native capture shells stage files.
        artifact_vault_dir: Directory where daemon-owned artifact files live.
        install_secret: Local install secret used by CLI/Workbench token exchange.
        provider_registration_secret: Narrow secret used only by local provider registration clients.
        token_audience: Expected audience for daemon tokens.
        token_ttl_seconds: Short-lived token lifetime in seconds.
        dev_mode: Whether development-only defaults are allowed.
    """

    model_config = SettingsConfigDict(env_prefix="WORKRECORDER_", extra="ignore")

    database_path: Path = Field(default=Path.home() / ".workrecorder" / "workrecorder.db")
    artifact_staging_dir: Path = Field(default=Path.home() / ".workrecorder" / "staging")
    artifact_vault_dir: Path = Field(default=Path.home() / ".workrecorder" / "artifacts")
    install_secret: str = Field(default="dev-install-secret", min_length=8)
    provider_registration_secret: str = Field(default="dev-provider-secret", min_length=8)
    native_capture_secret: str | None = Field(default=None, min_length=8)
    token_audience: str = "workrecorder-local-daemon"
    token_ttl_seconds: int = Field(default=600, ge=30, le=3600)
    disclosure_policy_path: Path | None = Field(default=Path.home() / ".workrecorder" / "disclosure_overrides.json")
    capture_route_min_provider_confidence: float = Field(default=0.55, ge=0.0, le=1.0)
    capture_route_min_secondary_overlap_ratio: float = Field(default=0.08, ge=0.0, le=1.0)
    capture_route_max_app_routes: int = Field(default=4, ge=1, le=16)
    capture_route_overlap_weight: float = Field(default=0.58, ge=0.0, le=1.0)
    capture_route_confidence_weight: float = Field(default=0.31, ge=0.0, le=1.0)
    capture_route_visible_area_weight: float = Field(default=0.06, ge=0.0, le=1.0)
    capture_route_frontmost_bonus: float = Field(default=0.03, ge=0.0, le=1.0)
    capture_route_z_order_base_bonus: float = Field(default=0.04, ge=0.0, le=1.0)
    capture_route_z_order_decay: float = Field(default=0.002, ge=0.0, le=1.0)
    active_capture_enabled: bool = True
    active_capture_auto_anchor_screenshots: bool = True
    active_capture_short_observation_window_ms: int = Field(default=5_000, ge=0)
    active_capture_max_session_duration_ms: int = Field(default=10 * 60 * 1000, ge=1_000)
    active_capture_max_keyframes_per_session: int = Field(default=64, ge=1, le=512)
    active_capture_scope_lost_grace_ms: int = Field(default=3_000, ge=0)
    active_capture_video_enabled: bool = True
    active_capture_video_max_bytes: int = Field(default=250 * 1024 * 1024, ge=1)
    active_capture_timeline_alignment_tolerance_ms: int = Field(default=500, ge=0)
    active_capture_pause_resume_enabled: bool = True
    active_capture_action_trace_enabled: bool = True
    active_capture_record_action_coordinates: bool = True
    active_capture_max_action_events_per_session: int = Field(default=20_000, ge=1, le=100_000)
    active_capture_min_keyframe_gap_ms: int = Field(default=500, ge=0)
    active_capture_click_settle_delay_ms: int = Field(default=300, ge=0)
    active_capture_scroll_stop_delay_ms: int = Field(default=400, ge=0)
    active_capture_hotkey_settle_delay_ms: int = Field(default=250, ge=0)
    active_capture_typing_pause_delay_ms: int = Field(default=500, ge=0)
    active_capture_idle_anchor_interval_ms: int = Field(default=30_000, ge=1_000)
    active_capture_visual_diff_threshold: float = Field(default=0.06, ge=0.0, le=1.0)
    active_capture_text_diff_threshold: float = Field(default=0.12, ge=0.0, le=1.0)
    active_capture_adaptive_settle_min_delay_ms: int = Field(default=250, ge=0)
    active_capture_adaptive_settle_max_wait_ms: int = Field(default=1_500, ge=0)
    active_capture_adaptive_settle_poll_interval_ms: int = Field(default=150, ge=1)
    active_capture_adaptive_settle_required_stable_samples: int = Field(default=2, ge=1, le=10)
    active_capture_settle_live_polling_enabled: bool = True
    active_capture_settle_probe_strategy: str = Field(default="hybrid", min_length=1)
    active_capture_settle_sample_budget: int = Field(default=12, ge=1, le=100)
    active_capture_settle_visual_diff_enabled: bool = True
    active_capture_settle_text_diff_enabled: bool = True
    active_capture_settle_provider_readiness_enabled: bool = True
    active_capture_settle_timeout_capture_enabled: bool = True
    active_capture_settle_capture_claim_lease_ms: int = Field(default=30_000, ge=1_000, le=300_000)
    active_capture_max_pending_trigger_candidates: int = Field(default=128, ge=1, le=10_000)
    active_capture_max_producer_events_per_session: int = Field(default=30_000, ge=1, le=200_000)
    active_capture_click_target_resolver_enabled: bool = True
    active_capture_click_target_high_confidence_threshold: float = Field(default=0.78, ge=0.0, le=1.0)
    active_capture_click_target_review_confidence_threshold: float = Field(default=0.55, ge=0.0, le=1.0)
    active_capture_click_target_max_candidates: int = Field(default=8, ge=1, le=32)
    active_capture_click_target_max_safe_label_chars: int = Field(default=80, ge=8, le=200)
    recording_target: Literal["macos", "linux"] = "macos"
    active_capture_vm_a11y_probe_enabled: bool = True
    active_capture_vm_a11y_probe_profile: Literal["mypcbench_v1", "osworld_gateway_v1", "linux_atspi_v1"] = "mypcbench_v1"
    active_capture_vm_a11y_probe_source: str = Field(default="dom_at_point", min_length=1)
    active_capture_vm_a11y_probe_url: str = Field(default="http://127.0.0.1:7071", min_length=1)
    active_capture_vm_a11y_probe_a11y_path: str = Field(default="/dom_at_point", min_length=1)
    active_capture_vm_a11y_probe_events_path: str = Field(default="/events", min_length=1)
    active_capture_vm_a11y_probe_events_limit: int = Field(default=20, ge=1, le=500)
    active_capture_vm_a11y_probe_events_poll_attempts: int = Field(default=12, ge=1, le=50)
    active_capture_vm_a11y_probe_events_poll_interval_seconds: float = Field(default=0.05, ge=0.0, le=5.0)
    active_capture_vm_a11y_probe_events_match_window_seconds: float = Field(default=2.0, ge=0.0, le=30.0)
    active_capture_vm_a11y_probe_click_log_url: str | None = None
    active_capture_vm_a11y_probe_click_log_path: str | None = None
    active_capture_vm_a11y_probe_click_log_ssh_enabled: bool = False
    active_capture_vm_a11y_probe_click_log_ssh_jump_host: str | None = None
    active_capture_vm_a11y_probe_click_log_ssh_host: str = Field(default="127.0.0.1", min_length=1)
    active_capture_vm_a11y_probe_click_log_ssh_port: int = Field(default=2222, ge=1, le=65535)
    active_capture_vm_a11y_probe_click_log_ssh_user: str = Field(default="user", min_length=1)
    active_capture_vm_a11y_probe_click_log_ssh_key_path: str | None = None
    active_capture_vm_a11y_probe_click_log_ssh_guest_path: str = Field(default="/tmp/clicks.jsonl", min_length=1)
    active_capture_vm_a11y_probe_click_log_ssh_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    active_capture_vm_a11y_probe_depth: int | None = Field(default=None, ge=1, le=64)
    active_capture_vm_a11y_probe_max_nodes: int | None = Field(default=None, ge=1, le=20_000)
    active_capture_vm_a11y_probe_periodic_depth: int | None = Field(default=None, ge=1, le=64)
    active_capture_vm_a11y_probe_periodic_max_nodes: int | None = Field(default=None, ge=1, le=20_000)
    active_capture_vm_a11y_probe_request_timeout_seconds: float = Field(default=5.0, ge=0.1, le=60.0)
    active_capture_vm_a11y_probe_vm_screen_width: int | None = Field(default=None, ge=1, le=16_384)
    active_capture_vm_a11y_probe_vm_screen_height: int | None = Field(default=None, ge=1, le=16_384)
    active_capture_vm_a11y_probe_title_bar_pt: float = Field(default=28.0, ge=0.0, le=200.0)
    active_capture_vm_a11y_probe_restart_backoff_seconds: float = Field(default=5.0, ge=0.1)
    active_capture_vm_a11y_probe_max_history_per_session: int = Field(default=1000, ge=1)
    active_capture_vm_a11y_probe_export_drain_timeout_seconds: float = Field(default=3.0, ge=0.0, le=120.0)
    active_capture_projection_max_timeline_steps: int = Field(default=500, ge=1, le=10_000)
    active_capture_projection_max_actions: int = Field(default=20_000, ge=1, le=100_000)
    active_capture_projection_max_safe_text_blocks: int = Field(default=128, ge=0, le=10_000)
    active_capture_projection_max_safe_text_chars: int = Field(default=256_000, ge=0, le=10_000_000)
    active_capture_projection_max_producer_diagnostics: int = Field(default=1_000, ge=0, le=100_000)
    safe_index_policy_version: str = Field(default="index_policy_v1", min_length=1)
    safe_index_max_text_chars: int = Field(default=256_000, ge=1, le=10_000_000)
    capture_post_commit_outbox_enabled: bool = True
    capture_post_commit_outbox_max_attempts: int = Field(default=3, ge=1, le=20)
    capture_post_commit_outbox_claim_limit: int = Field(default=20, ge=1, le=200)
    capture_post_commit_outbox_retry_backoff_ms: int = Field(default=1_000, ge=0)
    capture_post_commit_outbox_max_retry_delay_ms: int = Field(default=30_000, ge=0)
    capture_post_commit_outbox_stale_running_after_ms: int = Field(default=60_000, ge=1_000)
    capture_post_commit_outbox_worker_enabled: bool = True
    capture_post_commit_outbox_worker_poll_interval_ms: int = Field(default=1_000, ge=100)
    feishu_app_id: str | None = None
    feishu_folder_token: str | None = None
    feishu_api_base_url: str = "https://open.feishu.cn"
    dev_mode: bool = True


class SettingsLoader:
    """Construct settings objects for CLI, daemon, and tests."""

    def load(self) -> WorkRecorderSettings:
        """Load settings from the current environment.

        Returns:
            Runtime settings with defaults suitable for local P0 development.
        """

        return WorkRecorderSettings()
