import {
  ArtifactRole,
  ArtifactType,
  EvidenceKind,
  EvidencePhase,
  EvidenceSensitivity,
  EvidenceTrustState,
  ProviderCapability,
  ProviderCommandStatus,
  ProviderKey,
  ProviderKind,
  RedactionState,
  SourceType,
  WebEvidenceKind
} from "./contracts.js";
import type {
  BrowserTabRef,
  BrowserViewport,
  BrowserWindowRef,
  CollectEvidenceCommandEnvelope,
  CollectEvidenceResult,
  ContentEvidence,
  EvidenceDraft,
  ProviderHeartbeat,
  ProviderEvidenceBundle,
  ProviderSessionRegistration
} from "./contracts.js";
import {
  DAEMON_URL_STORAGE_KEY,
  ConnectionConfigMemo,
  DEFAULT_DAEMON_URL,
  DEFAULT_PROVIDER_REGISTRATION_SECRET,
  LOCAL_CONFIG_FILE,
  PROVIDER_SECRET_STORAGE_KEY,
  connectionConfigChanged,
  resolveConnectionConfig,
  type ResolvedConnectionConfig
} from "./connection_config.js";

const PROVIDER_KEY = ProviderKey.WebBrowserExtension;
const PROVIDER_WS_SUBPROTOCOL = "workrecorder-provider-v1";
const TOKEN_SUBPROTOCOL_PREFIX = "workrecorder-token.";
const SESSION_ID = `${chrome.runtime.id}:${Date.now()}`;
const HEARTBEAT_INTERVAL_MS = 1000;
const CAPABILITIES = [
  ProviderCapability.ResolveSource,
  ProviderCapability.CollectPageMetadata,
  ProviderCapability.CollectVisibleText,
  ProviderCapability.CollectSelectedText,
  ProviderCapability.CollectPageText,
  ProviderCapability.CollectReadabilityText,
  ProviderCapability.CollectSanitizedDom,
  ProviderCapability.CollectFullDom,
  ProviderCapability.MapSelection
] as const;

type TokenEnvelope = {
  ok: boolean;
  data?: { access_token: string };
};

let socket: WebSocket | null = null;
let connectionAttempt: Promise<void> | null = null;
let reconnectTimer: number | undefined;
let heartbeatTimer: number | undefined;
let activeConnectionConfig: ResolvedConnectionConfig | null = null;
const connectionConfigMemo = new ConnectionConfigMemo(loadDaemonConnectionConfig);

void connectProviderSession();

chrome.runtime.onStartup.addListener(() => {
  void connectProviderSession();
});

chrome.runtime.onInstalled.addListener(() => {
  void connectProviderSession();
});

chrome.action.onClicked.addListener(() => {
  void connectProviderSession();
  void sendHeartbeat();
});

chrome.runtime.onMessage.addListener((message) => {
  if (isContentReady(message)) {
    void connectProviderSession();
    void sendHeartbeat();
  }
  return false;
});

chrome.tabs.onActivated.addListener(() => {
  void sendHeartbeat();
});

chrome.tabs.onUpdated.addListener((_tabId, changeInfo) => {
  if (changeInfo.status === "complete" || changeInfo.url || changeInfo.title) {
    void sendHeartbeat();
  }
});

async function connectProviderSession(): Promise<void> {
  if (socket && (socket.readyState === WebSocket.CONNECTING || socket.readyState === WebSocket.OPEN)) {
    return;
  }
  if (connectionAttempt) {
    return connectionAttempt;
  }
  connectionAttempt = openProviderSession().finally(() => {
    connectionAttempt = null;
  });
  return connectionAttempt;
}

async function openProviderSession(): Promise<void> {
  try {
    const config = await daemonConnectionConfig();
    const token = await issueToken(config);
    const nextSocket = new WebSocket(`${webSocketURL(config)}/v1/providers/sessions/ws`, [
      PROVIDER_WS_SUBPROTOCOL,
      `${TOKEN_SUBPROTOCOL_PREFIX}${token}`
    ]);
    socket = nextSocket;
    nextSocket.onopen = () => {
      activeConnectionConfig = config;
      console.info("WorkRecorder Web provider session opened", { providerKey: PROVIDER_KEY, sessionId: SESSION_ID });
      void sendRegistration();
      heartbeatTimer = globalThis.setInterval(() => {
        void sendHeartbeat();
      }, HEARTBEAT_INTERVAL_MS);
    };
    nextSocket.onmessage = (event) => {
      void handleMessage(event.data);
    };
    nextSocket.onclose = () => {
      console.info("WorkRecorder Web provider session closed; reconnecting", { providerKey: PROVIDER_KEY });
      if (socket === nextSocket) {
        socket = null;
      }
      if (activeConnectionConfig === config) {
        activeConnectionConfig = null;
      }
      clearHeartbeat();
      resetConnectionConfigCache();
      scheduleReconnect();
    };
    nextSocket.onerror = () => {
      clearHeartbeat();
      resetConnectionConfigCache();
      nextSocket.close();
    };
  } catch {
    resetConnectionConfigCache();
    scheduleReconnect();
  }
}

async function sendRegistration(): Promise<void> {
  const routeHint = await activeRouteHint();
  const registration: ProviderSessionRegistration = {
    schema_version: 1,
    provider_key: PROVIDER_KEY,
    provider_session_id: SESSION_ID,
    provider_kind: ProviderKind.Source,
    display_name: "WorkRecorder Web Provider",
    app_name: browserAppName(),
    ...(routeHint.window ? { window: routeHint.window } : {}),
    ...(routeHint.tab ? { tab: routeHint.tab } : {}),
    ...(routeHint.viewport ? { viewport: routeHint.viewport } : {}),
    capabilities: [...CAPABILITIES],
    registered_at: new Date().toISOString(),
    ttl_ms: 15000,
    metadata: { extension_id: chrome.runtime.id, transport: "local_websocket_v1" }
  };
  sendJSON({ message_type: "provider_session_register", registration });
}

async function sendHeartbeat(): Promise<void> {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    await connectProviderSession();
    return;
  }
  if (await materializedConfigChanged()) {
    resetConnectionConfigCache();
    socket.close();
    return;
  }
  const routeHint = await activeRouteHint();
  const heartbeat: ProviderHeartbeat = {
    message_type: "provider_heartbeat",
    heartbeat: {
      provider_key: PROVIDER_KEY,
      provider_session_id: SESSION_ID,
      observed_at: new Date().toISOString(),
      ...(routeHint.window ? { window: routeHint.window } : {}),
      ...(routeHint.tab ? { tab: routeHint.tab } : {}),
      ...(routeHint.viewport ? { viewport: routeHint.viewport } : {}),
      metadata: { extension_id: chrome.runtime.id }
    }
  };
  sendJSON(heartbeat);
}

async function handleMessage(raw: unknown): Promise<void> {
  if (typeof raw !== "string") {
    return;
  }
  const envelope = JSON.parse(raw) as CollectEvidenceCommandEnvelope;
  if (envelope.message_type !== "collect_evidence") {
    return;
  }
  const result = await collectForCommand(envelope);
  sendJSON(result);
}

async function collectForCommand(envelope: CollectEvidenceCommandEnvelope): Promise<CollectEvidenceResult> {
  const command = envelope.command;
  try {
    console.info("WorkRecorder Web provider collect command received", {
      commandId: command.command_id,
      domCaptureMode: command.dom_capture_mode
    });
    const tab = await targetTabForCommand(command);
    if (!tab.id || !tab.url || !tab.windowId) {
      throw new Error("No routed browser tab available for Web evidence collection");
    }
    const parsedUrl = safeURL(tab.url);
    if (!parsedUrl) {
      throw new Error("Active tab URL is not capturable");
    }
    const sanitizedTabUrl = sanitizedURL(parsedUrl);
    await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ["dist/content.js"] });
    const collectionRegion =
      command.selection_in_surface ??
      command.attempt.selection_geometry.pixel_region ??
      command.attempt.selection_geometry.selected_region;
    const evidence = await collectEvidence(tab.id, command.dom_capture_mode, collectionRegion);
    const zoom = await chrome.tabs.getZoom(tab.id);
    const viewport = viewportFromEvidence(evidence, zoom);
    const tabRef = tabRefFor(tab, parsedUrl);
    const sourceBinding = {
      binding_id: `src_${crypto.randomUUID().replaceAll("-", "")}`,
      source_ref: {
        source_type: SourceType.Web,
        title: tab.title ?? sanitizedTabUrl,
        app_name: browserAppName(),
        url: sanitizedTabUrl,
        origin: parsedUrl.origin,
        connector_name: PROVIDER_KEY,
        external_id: String(tab.id),
        version: `tab:${tab.id}:${Date.now()}`
      },
      confidence: 0.86,
      resolved_at: new Date().toISOString(),
      provider_key: PROVIDER_KEY,
      provider_context_id: SESSION_ID,
      capabilities: [...CAPABILITIES]
    };
    const result: CollectEvidenceResult = {
      schema_version: 1,
      message_type: "collect_evidence_result",
      command_id: command.command_id,
      provider_key: PROVIDER_KEY,
      provider_session_id: SESSION_ID,
      status: ProviderCommandStatus.Succeeded,
      evidence_kind: WebEvidenceKind.Web,
      source_binding: sourceBinding,
      evidence_bundle: bundleForEvidence(
        evidence,
        tabRef,
        viewport,
        collectionRegion,
        sourceBinding,
        command.command_id
      ),
      diagnostics: {
        dom_capture_mode: command.dom_capture_mode,
        actual_dom_capture_mode: evidence.fullDom.captureMode,
        full_dom_truncated: evidence.fullDom.truncated,
        full_dom_node_count: evidence.fullDom.nodeCount,
        expected_tab_id: targetTabId(command) ?? null,
        actual_tab_id: String(tab.id),
        actual_window_id: String(tab.windowId)
      },
      completed_at: new Date().toISOString()
    };
    console.info("WorkRecorder Web provider collect command succeeded", {
      commandId: command.command_id,
      evidenceCount: result.evidence_bundle?.evidence.length ?? 0
    });
    return result;
  } catch (error) {
    console.warn("WorkRecorder Web provider collect command failed", {
      commandId: command.command_id,
      error: error instanceof Error ? error.message : "Unknown Web provider error"
    });
    return {
      schema_version: 1,
      message_type: "collect_evidence_result",
      command_id: command.command_id,
      provider_key: PROVIDER_KEY,
      provider_session_id: SESSION_ID,
      status: ProviderCommandStatus.Failed,
      evidence_kind: WebEvidenceKind.Web,
      evidence_bundle: undefined,
      diagnostics: {},
      error_message: error instanceof Error ? error.message : "Unknown Web provider error",
      completed_at: new Date().toISOString()
    };
  }
}

function bundleForEvidence(
  evidence: ContentEvidence,
  tab: BrowserTabRef,
  viewport: BrowserViewport,
  screenRegion: BrowserViewport["rect"],
  sourceBinding: ProviderEvidenceBundle["source_binding"],
  commandId: string
): ProviderEvidenceBundle {
  const capturedAt = new Date().toISOString();
  const pageMetadata = {
    url: tab.url,
    origin: tab.origin,
    title: tab.title,
    browser: tab.browser,
    tab_id: tab.tab_id,
    window_id: tab.window_id,
    provider: PROVIDER_KEY
  };
  const selectionMap = {
    binding_id: sourceBinding.binding_id,
    screen_region: screenRegion,
    viewport_region: evidence.selection.viewportRect ?? null,
    spans: evidence.selection.text
      ? [
          {
            selector: evidence.selection.selector ?? "selection",
            start: 0,
            end: evidence.selection.text.length,
            text: evidence.selection.text
          }
        ]
      : [],
    transforms: [],
    confidence: evidence.selection.confidence ?? (evidence.selection.text ? 0.72 : 0.42)
  };
  const drafts: EvidenceDraft[] = [
    jsonEvidence(EvidenceKind.PageMetadata, ArtifactType.PageMetadata, ArtifactRole.PageMetadata, pageMetadata, {
      sourceUri: tab.url,
      observedAt: capturedAt,
      commandId,
      sourceBindingId: sourceBinding.binding_id,
      sensitivity: EvidenceSensitivity.Internal,
      trustState: EvidenceTrustState.ProviderRedacted
    }),
    jsonEvidence(EvidenceKind.SelectionMap, ArtifactType.SelectionMap, ArtifactRole.SelectionMap, selectionMap, {
      sourceUri: `${tab.url}#selection`,
      observedAt: capturedAt,
      commandId,
      sourceBindingId: sourceBinding.binding_id,
      sensitivity: EvidenceSensitivity.Internal,
      trustState: EvidenceTrustState.ProviderRedacted
    }),
    jsonEvidence(
      EvidenceKind.FullDom,
      ArtifactType.BrowserFullDom,
      ArtifactRole.FullDom,
      {
        capture_mode: evidence.fullDom.captureMode,
        html: evidence.fullDom.html,
        text_content: evidence.fullDom.textContent,
        node_count: evidence.fullDom.nodeCount,
        truncated: evidence.fullDom.truncated,
        sanitizer_version: "full_dom_v2_privacy"
      },
      {
        sourceUri: `${tab.url}#dom`,
        observedAt: capturedAt,
        commandId,
        sourceBindingId: sourceBinding.binding_id,
        sensitivity: EvidenceSensitivity.HighSensitivity,
        trustState: EvidenceTrustState.Quarantined
      }
    ),
    jsonEvidence(EvidenceKind.PageMetadata, ArtifactType.PageMetadata, ArtifactRole.ProviderDiagnostics, { viewport }, {
      sourceUri: `${tab.url}#viewport`,
      observedAt: capturedAt,
      commandId,
      sourceBindingId: sourceBinding.binding_id,
      sensitivity: EvidenceSensitivity.Internal,
      trustState: EvidenceTrustState.ProviderRedacted,
      metadata: { diagnostic_kind: "viewport" }
    })
  ];
  appendTextEvidence(
    drafts,
    EvidenceKind.VisibleText,
    ArtifactType.BrowserVisibleText,
    evidence.visibleText,
    tab.url,
    commandId,
    sourceBinding.binding_id
  );
  appendPageTextEvidence(drafts, evidence, tab.url, commandId, sourceBinding.binding_id);
  appendTextEvidence(
    drafts,
    EvidenceKind.SelectedText,
    ArtifactType.BrowserSelectedText,
    evidence.selectedText,
    `${tab.url}#selection_text`,
    commandId,
    sourceBinding.binding_id,
    {
      selection_source: evidence.selection.source ?? "window_selection",
      selection_confidence: evidence.selection.confidence ?? null
    }
  );
  return {
    provider_key: PROVIDER_KEY,
    provider_session_id: SESSION_ID,
    command_id: commandId,
    status: ProviderCommandStatus.Succeeded,
    evidence_kind: WebEvidenceKind.Web,
    source_binding: sourceBinding,
    evidence: drafts,
    diagnostics: { actual_window_id: tab.window_id },
    completed_at: capturedAt
  };
}

function jsonEvidence(
  kind: EvidenceDraft["kind"],
  artifactType: EvidenceDraft["artifact_type"],
  role: EvidenceDraft["role"],
  value: unknown,
  options: {
    sourceUri: string;
    observedAt: string;
    commandId: string;
    sourceBindingId: string;
    sensitivity: EvidenceDraft["sensitivity"];
    trustState: EvidenceDraft["trust_state_claim"];
    metadata?: Record<string, string | number | boolean | null>;
  }
): EvidenceDraft {
  return {
    phase: EvidencePhase.Captured,
    kind,
    artifact_type: artifactType,
    role,
    payload: {
      content_type: "application/json",
      inline_content: JSON.stringify(value),
      payload_schema: kind,
      payload_version: "1"
    },
    locator: {
      source_uri: options.sourceUri,
      source_type: SourceType.Web
    },
    observed_at: options.observedAt,
    captured_at: options.observedAt,
    provenance: {
      provider_key: PROVIDER_KEY,
      provider_kind: ProviderKind.Source,
      provider_session_id: SESSION_ID,
      command_id: options.commandId,
      source_binding_id: options.sourceBindingId,
      parent_evidence_ids: [],
      input_artifact_ids: [],
      extractor: { name: PROVIDER_KEY, version: "p3_web_v1" }
    },
    sensitivity: options.sensitivity,
    trust_state_claim: options.trustState,
    redaction_state_claim:
      options.trustState === EvidenceTrustState.Quarantined ? RedactionState.Quarantined : RedactionState.Redacted,
    metadata: options.metadata ?? {}
  };
}

function textEvidence(
  kind: typeof EvidenceKind.VisibleText | typeof EvidenceKind.SelectedText,
  artifactType: typeof ArtifactType.BrowserVisibleText | typeof ArtifactType.BrowserSelectedText,
  role: typeof ArtifactRole.SourceText,
  content: string,
  sourceUri: string,
  commandId: string,
  sourceBindingId: string,
  metadata: Record<string, string | number | boolean | null> = {}
): EvidenceDraft {
  const capturedAt = new Date().toISOString();
  return {
    phase: EvidencePhase.Captured,
    kind,
    artifact_type: artifactType,
    role: role as EvidenceDraft["role"],
    payload: {
      content_type: "text/plain; charset=utf-8",
      inline_content: content,
      payload_schema: kind,
      payload_version: "1"
    },
    locator: {
      source_uri: sourceUri,
      source_type: SourceType.Web
    },
    observed_at: capturedAt,
    captured_at: capturedAt,
    provenance: {
      provider_key: PROVIDER_KEY,
      provider_kind: ProviderKind.Source,
      provider_session_id: SESSION_ID,
      command_id: commandId,
      source_binding_id: sourceBindingId,
      parent_evidence_ids: [],
      input_artifact_ids: [],
      extractor: { name: PROVIDER_KEY, version: "p3_web_v1" }
    },
    sensitivity: EvidenceSensitivity.Internal,
    trust_state_claim: EvidenceTrustState.ProviderRedacted,
    redaction_state_claim: RedactionState.Redacted,
    metadata
  };
}

function appendTextEvidence(
  drafts: EvidenceDraft[],
  kind: typeof EvidenceKind.VisibleText | typeof EvidenceKind.SelectedText,
  artifactType: typeof ArtifactType.BrowserVisibleText | typeof ArtifactType.BrowserSelectedText,
  content: string,
  sourceUri: string,
  commandId: string,
  sourceBindingId: string,
  metadata: Record<string, string | number | boolean | null> = {}
): void {
  if (content.trim().length === 0) {
    return;
  }
  drafts.push(textEvidence(kind, artifactType, ArtifactRole.SourceText, content, sourceUri, commandId, sourceBindingId, metadata));
}

function appendPageTextEvidence(
  drafts: EvidenceDraft[],
  evidence: ContentEvidence,
  sourceUri: string,
  commandId: string,
  sourceBindingId: string
): void {
  if (evidence.pageText.markdown.trim().length === 0 && evidence.pageText.plainText.trim().length === 0) {
    return;
  }
  drafts.push(
    jsonEvidence(
      EvidenceKind.PageText,
      ArtifactType.BrowserReadabilityMarkdown,
      ArtifactRole.SourceText,
      {
        markdown: evidence.pageText.markdown,
        plain_text: evidence.pageText.plainText,
        method: evidence.pageText.method,
        title: evidence.pageText.title ?? null,
        byline: evidence.pageText.byline ?? null,
        site_name: evidence.pageText.siteName ?? null,
        language: evidence.pageText.language ?? null,
        content_hash: evidence.pageText.contentHash ?? null,
        char_count: evidence.pageText.charCount,
        truncated: evidence.pageText.truncated,
        omitted_reasons: evidence.pageText.omittedReasons,
        frame_count: evidence.pageText.frameCount,
        shadow_root_count: evidence.pageText.shadowRootCount,
        extractor_version: evidence.pageText.extractorVersion
      },
      {
        sourceUri: `${sourceUri}#page_text`,
        observedAt: new Date().toISOString(),
        commandId,
        sourceBindingId,
        sensitivity: EvidenceSensitivity.Internal,
        trustState: EvidenceTrustState.ProviderRedacted,
        metadata: {
          page_text_truncated: evidence.pageText.truncated,
          page_text_char_count: evidence.pageText.charCount,
          frame_count: evidence.pageText.frameCount,
          shadow_root_count: evidence.pageText.shadowRootCount
        }
      }
    )
  );
}

async function activeRouteHint(): Promise<{
  tab?: BrowserTabRef;
  window?: BrowserWindowRef;
  viewport?: BrowserViewport;
}> {
  try {
    const tab = await activeTab();
    if (!tab.id || !tab.url || !tab.windowId) {
      return {};
    }
    const parsedUrl = safeURL(tab.url);
    if (!parsedUrl) {
      return {};
    }
    const browserWindow = await chrome.windows.get(tab.windowId);
    const zoom = await chrome.tabs.getZoom(tab.id);
    return {
      tab: tabRefFor(tab, parsedUrl),
      window: windowRefFor(browserWindow),
      viewport: {
        rect: { x: 0, y: 0, width: 1, height: 1, coordinate_space: "viewport_css_px" },
        device_pixel_ratio: 1,
        browser_zoom: zoom,
        scroll_x: 0,
        scroll_y: 0
      }
    };
  } catch {
    return {};
  }
}

async function activeTab(): Promise<chrome.tabs.Tab> {
  const primary = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  const fallback = await chrome.tabs.query({ active: true });
  const seen = new Set<number>();
  const candidates = [...primary, ...fallback].filter((tab) => {
    if (!tab.id || seen.has(tab.id)) {
      return false;
    }
    seen.add(tab.id);
    return true;
  });
  const capturable = candidates.find((tab) => Boolean(tab.id && tab.windowId && tab.url && safeURL(tab.url)));
  if (!capturable) {
    throw new Error("No active capturable browser tab");
  }
  return capturable;
}

async function targetTabForCommand(command: CollectEvidenceCommandEnvelope["command"]): Promise<chrome.tabs.Tab> {
  const expectedTabId = targetTabId(command);
  if (expectedTabId === undefined) {
    throw new Error("Collect command is missing routed target_tab_id");
  }
  const tab = await chrome.tabs.get(Number(expectedTabId));
  if (!tab.id || !tab.windowId || !tab.url || !safeURL(tab.url)) {
    throw new Error("Routed browser tab is not capturable");
  }
  const expectedWindowId = targetWindowId(command);
  if (expectedWindowId !== undefined && String(tab.windowId) !== expectedWindowId) {
    throw new Error("Routed browser tab moved to a different window");
  }
  return tab;
}

function targetTabId(command: CollectEvidenceCommandEnvelope["command"]): string | undefined {
  const value = command.metadata?.target_tab_id;
  if (typeof value === "string" && /^\d+$/.test(value)) {
    return value;
  }
  if (typeof value === "number" && Number.isInteger(value) && value >= 0) {
    return String(value);
  }
  return undefined;
}

function targetWindowId(command: CollectEvidenceCommandEnvelope["command"]): string | undefined {
  const value = command.metadata?.target_window_id;
  if (typeof value === "string" && value.length > 0) {
    return value;
  }
  if (typeof value === "number" && Number.isInteger(value)) {
    return String(value);
  }
  return undefined;
}

async function collectEvidence(
  tabId: number,
  domCaptureMode: "full" | "sanitized_selection",
  screenRegion: ContentEvidence["selection"]["viewportRect"] | null | undefined
): Promise<ContentEvidence> {
  const response = await chrome.tabs.sendMessage(tabId, {
    type: "workrecorder.collectEvidence",
    domCaptureMode,
    screenRegion
  });
  return response as ContentEvidence;
}

function viewportFromEvidence(evidence: ContentEvidence, zoom: number): BrowserViewport {
  return {
    rect: {
      x: 0,
      y: 0,
      width: evidence.viewport.width,
      height: evidence.viewport.height,
      coordinate_space: "viewport_css_px"
    },
    device_pixel_ratio: evidence.viewport.devicePixelRatio,
    browser_zoom: zoom,
    scroll_x: evidence.viewport.scrollX,
    scroll_y: evidence.viewport.scrollY
  };
}

function tabRefFor(tab: chrome.tabs.Tab, parsedUrl: URL): BrowserTabRef {
  if (!tab.id || !tab.windowId || !tab.url) {
    throw new Error("Tab is missing id, window, or URL");
  }
  const url = sanitizedURL(parsedUrl);
  return {
    browser: browserKind(),
    tab_id: String(tab.id),
    window_id: String(tab.windowId),
    url,
    origin: parsedUrl.origin,
    title: tab.title ?? url
  };
}

function windowRefFor(browserWindow: chrome.windows.Window): BrowserWindowRef {
  const screenRect =
    browserWindow.left === undefined ||
    browserWindow.top === undefined ||
    browserWindow.width === undefined ||
    browserWindow.height === undefined
      ? undefined
      : {
          x: browserWindow.left,
          y: browserWindow.top,
          width: Math.max(browserWindow.width, 1),
          height: Math.max(browserWindow.height, 1),
          coordinate_space: "macos_global" as const
        };
  return {
    window_id: String(browserWindow.id ?? "unknown"),
    ...(screenRect ? { screen_rect: screenRect } : {})
  };
}

async function issueToken(config: ResolvedConnectionConfig): Promise<string> {
  try {
    const response = await fetch(`${config.daemonUrl}/v1/auth/tokens`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "x-workrecorder-provider-secret": config.providerRegistrationSecret
      },
      body: JSON.stringify({
        actor_id: "browser-extension",
        display_name: "WorkRecorder Browser Extension",
        scopes: ["register_provider_context"]
      })
    });
    const envelope = (await response.json()) as TokenEnvelope;
    if (!envelope.ok || !envelope.data?.access_token) {
      resetConnectionConfigCache();
      throw new Error("WorkRecorder token issue failed");
    }
    return envelope.data.access_token;
  } catch (error) {
    resetConnectionConfigCache();
    if (error instanceof Error) {
      throw error;
    }
    throw new Error("WorkRecorder token issue failed");
  }
}

function browserKind(): "chrome" | "edge" | "arc" | "unknown" {
  const userAgent = navigator.userAgent.toLowerCase();
  if (userAgent.includes("edg/")) {
    return "edge";
  }
  if (userAgent.includes("chrome/")) {
    return "chrome";
  }
  return "unknown";
}

function browserAppName(): string {
  const kind = browserKind();
  if (kind === "edge") {
    return "Microsoft Edge";
  }
  if (kind === "arc") {
    return "Arc";
  }
  return "Google Chrome";
}

function safeURL(value: string): URL | null {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:" ? url : null;
  } catch {
    return null;
  }
}

function sanitizedURL(value: URL): string {
  const copy = new URL(value.href);
  copy.search = "";
  copy.hash = "";
  return copy.href;
}

function webSocketURL(config: ResolvedConnectionConfig): string {
  const url = new URL(config.daemonUrl);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.origin;
}

async function daemonConnectionConfig(): Promise<ResolvedConnectionConfig> {
  return connectionConfigMemo.load();
}

function resetConnectionConfigCache(): void {
  connectionConfigMemo.invalidate();
}

async function loadDaemonConnectionConfig(): Promise<ResolvedConnectionConfig> {
  const [materialized, stored] = await Promise.all([
    localConfig(),
    chrome.storage.local.get([DAEMON_URL_STORAGE_KEY, PROVIDER_SECRET_STORAGE_KEY])
  ]);
  const config = resolveConnectionConfig(materialized, {
    daemonUrl: stored[DAEMON_URL_STORAGE_KEY],
    providerRegistrationSecret: stored[PROVIDER_SECRET_STORAGE_KEY]
  });
  if (config.staleStorageKeys.length > 0) {
    await chrome.storage.local.remove(config.staleStorageKeys);
  }
  return config;
}

async function materializedConfigChanged(): Promise<boolean> {
  if (!activeConnectionConfig) {
    return false;
  }
  const latest = await loadDaemonConnectionConfig();
  return connectionConfigChanged(activeConnectionConfig, latest);
}

async function localConfig(): Promise<{ daemonUrl?: string; providerRegistrationSecret?: string }> {
  try {
    const response = await fetch(chrome.runtime.getURL(LOCAL_CONFIG_FILE), { cache: "no-store" });
    if (!response.ok) {
      return {};
    }
    const payload = (await response.json()) as { daemon_url?: unknown; provider_registration_secret?: unknown };
    return {
      ...(typeof payload.daemon_url === "string" ? { daemonUrl: payload.daemon_url } : {}),
      ...(typeof payload.provider_registration_secret === "string" && payload.provider_registration_secret.length >= 8
        ? { providerRegistrationSecret: payload.provider_registration_secret }
        : {})
    };
  } catch {
    return {};
  }
}

function sendJSON(value: unknown): void {
  if (!socket || socket.readyState !== WebSocket.OPEN) {
    return;
  }
  socket.send(JSON.stringify(value));
}

function scheduleReconnect(): void {
  if (reconnectTimer !== undefined) {
    return;
  }
  reconnectTimer = globalThis.setTimeout(() => {
    reconnectTimer = undefined;
    void connectProviderSession();
  }, 1500);
}

function clearHeartbeat(): void {
  if (heartbeatTimer !== undefined) {
    globalThis.clearInterval(heartbeatTimer);
    heartbeatTimer = undefined;
  }
}

function isContentReady(message: unknown): message is { type: "workrecorder.contentReady" } {
  return (
    typeof message === "object" &&
    message !== null &&
    "type" in message &&
    (message as { type?: unknown }).type === "workrecorder.contentReady"
  );
}
