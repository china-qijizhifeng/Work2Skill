export const ProviderKey = { WebBrowserExtension: "web.browser_extension" } as const;
export type ProviderKey = (typeof ProviderKey)[keyof typeof ProviderKey];

export const SourceType = {
  Web: "web",
  DesktopWindow: "desktop_window",
  SourceRecord: "source_record",
  Mock: "mock",
  Unknown: "unknown"
} as const;
export type SourceType = (typeof SourceType)[keyof typeof SourceType];

export const ProviderKind = { Source: "source", SystemEvidence: "system_evidence", Enrichment: "enrichment" } as const;
export type ProviderKind = (typeof ProviderKind)[keyof typeof ProviderKind];

export const ProviderCapability = {
  ResolveSource: "resolve_source",
  CollectPageMetadata: "collect_page_metadata",
  CollectVisibleText: "collect_visible_text",
  CollectSelectedText: "collect_selected_text",
  CollectPageText: "collect_page_text",
  CollectReadabilityText: "collect_readability_text",
  CollectSanitizedDom: "collect_sanitized_dom",
  CollectFullDom: "collect_full_dom",
  MapSelection: "map_selection"
} as const;
export type ProviderCapability = (typeof ProviderCapability)[keyof typeof ProviderCapability];

export const EvidencePhase = { Captured: "captured", Enriched: "enriched", Indexed: "indexed" } as const;
export type EvidencePhase = (typeof EvidencePhase)[keyof typeof EvidencePhase];

export const EvidenceKind = {
  PageMetadata: "page_metadata",
  SelectionMap: "selection_map",
  FullDom: "full_dom",
  PageText: "page_text",
  VisibleText: "visible_text",
  SelectedText: "selected_text",
  ProviderDiagnostics: "provider_diagnostics"
} as const;
export type EvidenceKind = (typeof EvidenceKind)[keyof typeof EvidenceKind];

export const ArtifactType = {
  PageMetadata: "page_metadata",
  SelectionMap: "selection_map",
  BrowserFullDom: "browser_full_dom",
  BrowserReadabilityMarkdown: "browser_readability_markdown",
  BrowserVisibleText: "browser_visible_text",
  BrowserSelectedText: "browser_selected_text"
} as const;
export type ArtifactType = (typeof ArtifactType)[keyof typeof ArtifactType];

export const ArtifactRole = {
  PageMetadata: "page_metadata",
  SelectionMap: "selection_map",
  FullDom: "full_dom",
  SourceText: "source_text",
  ProviderDiagnostics: "provider_diagnostics"
} as const;
export type ArtifactRole = (typeof ArtifactRole)[keyof typeof ArtifactRole];

export const EvidenceSensitivity = {
  Public: "public",
  Internal: "internal",
  Sensitive: "sensitive",
  HighSensitivity: "high_sensitivity"
} as const;
export type EvidenceSensitivity = (typeof EvidenceSensitivity)[keyof typeof EvidenceSensitivity];

export const EvidenceTrustState = {
  Untrusted: "untrusted",
  ProviderRedacted: "provider_redacted",
  DlpPassed: "dlp_passed",
  Quarantined: "quarantined",
  Blocked: "blocked"
} as const;
export type EvidenceTrustState = (typeof EvidenceTrustState)[keyof typeof EvidenceTrustState];

export const RedactionState = {
  None: "none",
  Redacted: "redacted",
  Quarantined: "quarantined",
  Blocked: "blocked"
} as const;
export type RedactionState = (typeof RedactionState)[keyof typeof RedactionState];

export const ProviderCommandStatus = {
  Succeeded: "succeeded",
  Unsupported: "unsupported",
  Failed: "failed",
  Timeout: "timeout"
} as const;
export type ProviderCommandStatus = (typeof ProviderCommandStatus)[keyof typeof ProviderCommandStatus];

export const WebEvidenceKind = { Web: "web" } as const;
export type WebEvidenceKind = (typeof WebEvidenceKind)[keyof typeof WebEvidenceKind];

export const DomCaptureMode = { Full: "full", SanitizedSelection: "sanitized_selection" } as const;
export type DomCaptureMode = (typeof DomCaptureMode)[keyof typeof DomCaptureMode];

export type CoordinateSpace = "macos_global" | "screen_px" | "viewport_css_px" | "page_css_px";

export type Rect = {
  x: number;
  y: number;
  width: number;
  height: number;
  coordinate_space: CoordinateSpace;
};

export type JsonScalar = string | number | boolean | null;

export type EvidencePayloadRef = {
  content_type: string;
  inline_content?: string | null;
  storage_uri?: string | null;
  byte_size?: number | null;
  sha256?: string | null;
  payload_schema?: string | null;
  payload_version: string;
};

export type ExtractorRef = {
  name: string;
  version: string;
};

export type EvidenceLocator = {
  source_uri: string;
  source_type: SourceType;
  coordinate_space?: string | null;
  bbox?: Rect | null;
  text_range?: { start: number; end: number } | null;
  selector?: string | null;
  path?: string | null;
  metadata?: Record<string, JsonScalar>;
};

export type EvidenceProvenance = {
  provider_key: string;
  provider_kind: ProviderKind;
  provider_session_id?: string | null;
  command_id?: string | null;
  route_id?: string | null;
  source_binding_id?: string | null;
  parent_evidence_ids?: string[];
  input_artifact_ids?: string[];
  extractor: ExtractorRef;
};

export type EvidenceDraft = {
  phase: EvidencePhase;
  kind: EvidenceKind;
  artifact_type: ArtifactType;
  role: ArtifactRole;
  payload: EvidencePayloadRef;
  locator: EvidenceLocator;
  observed_at: string;
  captured_at: string;
  provenance: EvidenceProvenance;
  sensitivity: EvidenceSensitivity;
  trust_state_claim: EvidenceTrustState;
  redaction_state_claim: RedactionState;
  metadata?: Record<string, JsonScalar>;
};

export type BrowserTabRef = {
  browser: string;
  tab_id: string;
  window_id: string;
  url: string;
  origin: string;
  title: string;
};

export type BrowserViewport = {
  rect: Rect;
  device_pixel_ratio: number;
  browser_zoom: number;
  scroll_x: number;
  scroll_y: number;
};

export type BrowserWindowRef = {
  window_id: string;
  native_window_id?: string;
  screen_rect?: Rect;
};

export type ProviderSessionRegistration = {
  schema_version: 1;
  provider_key: typeof ProviderKey.WebBrowserExtension;
  provider_session_id: string;
  provider_kind: typeof ProviderKind.Source;
  display_name: string;
  app_name: string;
  window_id?: string;
  window?: BrowserWindowRef;
  tab?: BrowserTabRef;
  viewport?: BrowserViewport;
  capabilities: string[];
  registered_at: string;
  ttl_ms: number;
  metadata?: Record<string, string | number | boolean | null>;
};

export type ProviderHeartbeat = {
  message_type: "provider_heartbeat";
  heartbeat: {
    provider_key: typeof ProviderKey.WebBrowserExtension;
    provider_session_id: string;
    observed_at: string;
    tab?: BrowserTabRef;
    viewport?: BrowserViewport;
    window?: BrowserWindowRef;
    metadata?: Record<string, string | number | boolean | null>;
  };
};

export type DetectedSurface = {
  surface_id: string;
  kind: string;
  app_name: string;
  title?: string | null;
  process_id?: number | null;
  window_id?: string | null;
  frame?: Rect | null;
  overlap_ratio: number;
  confidence: number;
  capabilities?: string[];
};

export type CollectEvidenceCommandEnvelope = {
  schema_version: number;
  message_type: "collect_evidence";
  command: {
    command_id: string;
    provider_key: typeof ProviderKey.WebBrowserExtension;
    attempt: {
      selection_geometry: {
        selected_region: Rect;
        pixel_region?: Rect | null;
      };
    };
    surface?: DetectedSurface | null;
    selection_in_surface?: Rect | null;
    deadline_ms: number;
    dom_capture_mode: DomCaptureMode;
    metadata?: Record<string, string | number | boolean | null>;
  };
  sent_at: string;
};

export type SourceBinding = {
  binding_id: string;
  source_ref: {
    source_type: typeof SourceType.Web;
    title: string;
    app_name?: string;
    url: string;
    origin: string;
    connector_name: typeof ProviderKey.WebBrowserExtension;
    external_id?: string;
    version?: string;
  };
  confidence: number;
  resolved_at: string;
  provider_key: typeof ProviderKey.WebBrowserExtension;
  provider_context_id: string;
  capabilities: string[];
};

export type CollectEvidenceResult = {
  schema_version: 1;
  message_type: "collect_evidence_result";
  command_id: string;
  provider_key: typeof ProviderKey.WebBrowserExtension;
  provider_session_id: string;
  status: ProviderCommandStatus;
  evidence_kind: WebEvidenceKind;
  source_binding?: SourceBinding;
  evidence_bundle?: ProviderEvidenceBundle;
  diagnostics?: Record<string, string | number | boolean | null>;
  error_message?: string;
  completed_at: string;
};

export type ProviderEvidenceBundle = {
  provider_key: typeof ProviderKey.WebBrowserExtension;
  provider_session_id: string;
  command_id: string;
  status: ProviderCommandStatus;
  evidence_kind: WebEvidenceKind;
  source_binding: SourceBinding;
  evidence: EvidenceDraft[];
  diagnostics?: Record<string, JsonScalar>;
  completed_at: string;
};

export type ContentEvidence = {
  selectedText: string;
  visibleText: string;
  fullDom: {
    captureMode: DomCaptureMode;
    html: string;
    textContent: string;
    nodeCount: number;
    truncated: boolean;
  };
  pageText: {
    markdown: string;
    plainText: string;
    method: string;
    title?: string;
    byline?: string;
    siteName?: string;
    language?: string;
    contentHash?: string;
    charCount: number;
    truncated: boolean;
    omittedReasons: string[];
    frameCount: number;
    shadowRootCount: number;
    extractorVersion: string;
  };
  selection: {
    selector?: string;
    text: string;
    viewportRect?: Rect;
    source?: "browser_dom_region" | "window_selection";
    confidence?: number;
  };
  viewport: {
    width: number;
    height: number;
    devicePixelRatio: number;
    scrollX: number;
    scrollY: number;
  };
};
