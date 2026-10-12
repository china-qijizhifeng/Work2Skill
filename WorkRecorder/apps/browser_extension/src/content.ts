const MAX_TEXT_CHARS = 64000;
const MAX_PAGE_TEXT_CHARS = 250000;
const MAX_DOM_CHARS = 2_000_000;
const SENSITIVE_PATTERN = /token|csrf|xsrf|secret|password|session|credential|authorization|auth|jwt|api[-_]?key/i;
const SENSITIVE_ELEMENT_HINT_PATTERN = /csrf|xsrf|secret|password|credential|authorization|bearer|jwt|api[-_]?key/i;
const SENSITIVE_ATTRIBUTE_NAME_PATTERN =
  /(?:^|[-_:])(access[-_]?token|auth[-_]?token|session[-_]?id|csrf[-_]?token|xsrf[-_]?token|api[-_]?key|secret|password|credential|authorization|bearer|jwt|recovery[-_]?code|totp)(?:$|[-_:])/i;
const STRUCTURAL_ATTRIBUTE_NAMES = new Set([
  "class",
  "id",
  "role",
  "aria-label",
  "aria-labelledby",
  "data-testid",
  "data-test-id",
  "data-test",
  "data-turn",
  "data-turn-id",
  "data-turn-id-container",
  "data-scroll-anchor",
  "data-scroll-root",
  "data-is-intersecting"
]);
const SECRET_VALUE_PATTERNS = [
  /(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/=-]+/gi,
  /((?:api[-_ ]?key|token|secret|password|credential|jwt|session|csrf|xsrf)\s*[:=]\s*)[^\s"'<>]{3,}/gi,
  /\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9_=-]{6,}\b/gi,
  /\bAKIA[0-9A-Z]{16}\b/g,
  /\b[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g
];

type Rect = {
  x: number;
  y: number;
  width: number;
  height: number;
  coordinate_space: "viewport_css_px";
};

type ScreenRect = {
  x: number;
  y: number;
  width: number;
  height: number;
  coordinate_space: "macos_global" | "screen_px" | "viewport_css_px" | "page_css_px";
};

type ContentEvidence = {
  selectedText: string;
  visibleText: string;
  fullDom: {
    captureMode: "full" | "sanitized_selection";
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

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!isCollectMessage(message)) {
    return false;
  }
  sendResponse(collectEvidence(message.domCaptureMode, message.screenRegion));
  return true;
});

chrome.runtime.sendMessage({ type: "workrecorder.contentReady" }).catch(() => {
  // The background provider session is best-effort; evidence is still only
  // collected when the daemon sends a command.
});
document.documentElement.dataset.workrecorderProvider = "content-ready";

function isCollectMessage(
  message: unknown
): message is { type: string; domCaptureMode: "full" | "sanitized_selection"; screenRegion?: ScreenRect } {
  return (
    typeof message === "object" &&
    message !== null &&
    "type" in message &&
    (message as { type?: unknown }).type === "workrecorder.collectEvidence"
  );
}

function collectEvidence(
  domCaptureMode: "full" | "sanitized_selection" = "full",
  screenRegion?: ScreenRect
): ContentEvidence {
  const selection = selectionEvidence(screenRegion);
  const fullDom = collectFullDom(domCaptureMode, selection.selector);
  const selectedText = selection.isSensitive ? "" : redactSensitiveText(selection.text).slice(0, 16000);
  return {
    selectedText,
    visibleText: collectVisibleText(),
    fullDom,
    pageText: collectPageText(),
    selection: { ...selection, text: selectedText },
    viewport: {
      width: window.innerWidth,
      height: window.innerHeight,
      devicePixelRatio: window.devicePixelRatio || 1,
      scrollX: window.scrollX,
      scrollY: window.scrollY
    }
  };
}

function collectPageText(): ContentEvidence["pageText"] {
  const omittedReasons: string[] = [];
  const blocks = collectReadableBlocks(document.body, omittedReasons);
  const readableText = blocks.join("\n");
  const fallback = collectApplicationTextFallback(readableText);
  const useFallback =
    fallback !== undefined && (readableText.length < 400 || fallback.text.length > readableText.length * 1.8);
  const textBlocks = useFallback ? fallback.blocks : blocks;
  if (useFallback) {
    omittedReasons.push(`readable_blocks_sparse_inner_text_fallback:${fallback.source}`);
  }
  const plainText = textBlocks.join("\n").slice(0, MAX_PAGE_TEXT_CHARS);
  const title = normalizeText(document.title);
  const markdownParts = title ? [`# ${title}`, "", ...textBlocks] : textBlocks;
  const markdown = markdownParts.join("\n").slice(0, MAX_PAGE_TEXT_CHARS);
  const frameCount = document.querySelectorAll("iframe, frame").length;
  const shadowRootCount = countOpenShadowRoots(document.documentElement);
  if (frameCount > 0) {
    omittedReasons.push("cross_origin_or_uninspected_frames_may_be_partial");
  }
  if (isLikelyPDFDocument()) {
    omittedReasons.push("pdf_text_layer_may_be_partial");
  }
  return {
    markdown,
    plainText,
    method: useFallback ? "dom_text_snapshot_v1+inner_text_fallback" : "dom_text_snapshot_v1",
    title: title || undefined,
    siteName: siteName(),
    language: document.documentElement.lang || undefined,
    contentHash: simpleHash(plainText),
    charCount: plainText.length,
    truncated: markdown.length >= MAX_PAGE_TEXT_CHARS || plainText.length >= MAX_PAGE_TEXT_CHARS,
    omittedReasons: Array.from(new Set(omittedReasons)),
    frameCount,
    shadowRootCount,
    extractorVersion: "browser_page_text_v1"
  };
}

function collectApplicationTextFallback(existingText: string): { text: string; blocks: string[]; source: string } | undefined {
  const roots = candidateTextRoots();
  let best: { text: string; blocks: string[]; source: string; score: number } | undefined;
  for (const root of roots) {
    if (!isVisible(root) || hasSensitiveAncestor(root)) {
      continue;
    }
    const blocks = innerTextBlocks(root);
    const text = blocks.join("\n").slice(0, MAX_PAGE_TEXT_CHARS);
    if (text.length <= existingText.length || text.length < 20) {
      continue;
    }
    const source = fallbackSourceName(root);
    const score = scoreFallbackText(root, text, source);
    if (!best || score > best.score) {
      best = { text, blocks, source, score };
    }
  }
  return best ? { text: best.text, blocks: best.blocks, source: best.source } : undefined;
}

function candidateTextRoots(): HTMLElement[] {
  const selectors = [
    "main",
    "[role='main']",
    "article",
    "#thread",
    "[data-scroll-root]",
    "[data-workrecorder-text-root]",
    "body"
  ];
  const seen = new Set<HTMLElement>();
  const roots: HTMLElement[] = [];
  for (const selector of selectors) {
    for (const element of Array.from(document.querySelectorAll(selector))) {
      if (element instanceof HTMLElement && !seen.has(element)) {
        seen.add(element);
        roots.push(element);
      }
    }
  }
  if (document.body && !seen.has(document.body)) {
    roots.push(document.body);
  }
  return roots;
}

function innerTextBlocks(root: HTMLElement): string[] {
  return filteredVisibleTextBlocks(root).slice(0, 6000);
}

function filteredVisibleTextBlocks(root: Element | DocumentFragment, visited: WeakSet<Node> = new WeakSet()): string[] {
  if (visited.has(root)) {
    return [];
  }
  visited.add(root);
  const blocks: string[] = [];
  let currentLength = 0;
  const ownerDocument = root.ownerDocument ?? document;
  const walker = ownerDocument.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  while (walker.nextNode() && currentLength < MAX_PAGE_TEXT_CHARS) {
    const parent = walker.currentNode.parentElement;
    if (!parent || !isVisible(parent) || hasSensitiveAncestor(parent) || shouldSkipApplicationTextElement(parent)) {
      continue;
    }
    const text = redactSensitiveText(normalizeText(walker.currentNode.textContent ?? ""));
    if (text && !containsSecretValue(text)) {
      blocks.push(text);
      currentLength += text.length + 1;
    }
  }
  if (root.nodeType === Node.ELEMENT_NODE || root.nodeType === Node.DOCUMENT_FRAGMENT_NODE) {
    const elementWalker = ownerDocument.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
    while (elementWalker.nextNode() && currentLength < MAX_PAGE_TEXT_CHARS) {
      const element = elementWalker.currentNode as HTMLElement;
      const shadow = element.shadowRoot;
      if (shadow) {
        for (const shadowBlock of filteredVisibleTextBlocks(shadow, visited)) {
          blocks.push(shadowBlock);
          currentLength += shadowBlock.length + 1;
          if (currentLength >= MAX_PAGE_TEXT_CHARS) {
            break;
          }
        }
      }
    }
  }
  return dedupeAdjacent(blocks);
}

function shouldSkipApplicationTextElement(element: Element): boolean {
  const tag = element.tagName.toLowerCase();
  if (["button", "input", "textarea", "select", "option"].includes(tag)) {
    return true;
  }
  return shouldSkipReadableElement(element);
}

function fallbackSourceName(element: HTMLElement): string {
  if (element.id) {
    return `#${element.id}`;
  }
  const role = element.getAttribute("role");
  if (role) {
    return `[role=${role}]`;
  }
  return element.tagName.toLowerCase();
}

function scoreFallbackText(element: HTMLElement, text: string, source: string): number {
  let score = Math.min(text.length, MAX_PAGE_TEXT_CHARS);
  const tag = element.tagName.toLowerCase();
  if (tag === "main" || source === "[role=main]" || tag === "article") {
    score += 5000;
  }
  if (source === "body") {
    score -= 2500;
  }
  const lineCount = text.split("\n").length;
  if (lineCount > 12) {
    score += 1000;
  }
  return score;
}

function isLikelyPDFDocument(): boolean {
  return (
    document.contentType === "application/pdf" ||
    /\.pdf(?:$|[?#])/i.test(window.location.href) ||
    Boolean(document.querySelector("embed[type='application/pdf'], iframe[src$='.pdf']"))
  );
}

function collectReadableBlocks(
  root: Element | DocumentFragment | null,
  omittedReasons: string[],
  visited: WeakSet<Node> = new WeakSet()
): string[] {
  if (!root) {
    return [];
  }
  if (visited.has(root)) {
    return [];
  }
  visited.add(root);
  const blocks: string[] = [];
  let currentLength = 0;
  const ownerDocument = root.ownerDocument ?? document;
  const walker = ownerDocument.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
  const pushBlock = (value: string): void => {
    if (!value) {
      return;
    }
    blocks.push(value);
    currentLength += value.length + 1;
  };
  const visit = (element: Element): void => {
    if (!isVisible(element) || hasSensitiveAncestor(element) || shouldSkipReadableElement(element)) {
      return;
    }
    const tag = element.tagName.toLowerCase();
    if (tag !== "table" && hasAncestorTag(element, "table")) {
      return;
    }
    if (tag === "table") {
      const table = tableToMarkdown(element as HTMLTableElement);
      if (table) {
        pushBlock(table);
      }
      return;
    }
    if (isAriaTableElement(element) && !hasAncestorAriaTable(element)) {
      const table = ariaTableToMarkdown(element);
      if (table) {
        pushBlock(table);
      }
      return;
    }
    if (tag === "iframe" || tag === "frame") {
      const frameBlocks = collectFrameBlocks(element as HTMLIFrameElement, omittedReasons, visited);
      for (const frameBlock of frameBlocks) {
        pushBlock(frameBlock);
      }
      return;
    }
    if (["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "pre", "code", "blockquote", "td", "th", "caption"].includes(tag)) {
      const value = redactSensitiveText(visibleTextForElement(element));
      if (value) {
        pushBlock(prefixForTag(tag, value));
      }
    }
    const shadow = (element as HTMLElement).shadowRoot;
    if (shadow) {
      omittedReasons.push("open_shadow_root_included");
      for (const shadowBlock of collectReadableBlocks(shadow, omittedReasons, visited)) {
        pushBlock(shadowBlock);
      }
    }
  };
  if (root.nodeType === Node.ELEMENT_NODE) {
    visit(root as Element);
  }
  while (walker.nextNode() && currentLength < MAX_PAGE_TEXT_CHARS) {
    visit(walker.currentNode as Element);
  }
  return dedupeAdjacent(blocks).slice(0, 4000);
}

function collectFrameBlocks(
  frame: HTMLIFrameElement,
  omittedReasons: string[],
  visited: WeakSet<Node>
): string[] {
  try {
    const frameDocument = frame.contentDocument;
    if (!frameDocument?.body) {
      omittedReasons.push("frame_without_readable_document");
      return [];
    }
    omittedReasons.push("same_origin_frame_included");
    return collectReadableBlocks(frameDocument.body, omittedReasons, visited);
  } catch {
    omittedReasons.push("cross_origin_frame_omitted");
    return [];
  }
}

function shouldSkipReadableElement(element: Element): boolean {
  const tag = element.tagName.toLowerCase();
  if (["script", "style", "template", "noscript", "svg", "canvas", "nav", "header", "footer", "aside"].includes(tag)) {
    return true;
  }
  const role = element.getAttribute("role")?.toLowerCase() ?? "";
  if (["navigation", "banner", "contentinfo", "complementary", "search"].includes(role)) {
    return true;
  }
  return hasReadableNoiseAncestor(element);
}

function hasReadableNoiseAncestor(element: Element): boolean {
  for (let current = element.parentElement; current; current = current.parentElement) {
    const tag = current.tagName.toLowerCase();
    const role = current.getAttribute("role")?.toLowerCase() ?? "";
    if (
      ["nav", "header", "footer", "aside"].includes(tag) ||
      ["navigation", "banner", "contentinfo", "complementary", "search"].includes(role)
    ) {
      return true;
    }
  }
  return false;
}

function prefixForTag(tag: string, value: string): string {
  if (/h[1-6]/.test(tag)) {
    return `${"#".repeat(Number(tag.slice(1)))} ${value}`;
  }
  if (tag === "li") {
    return `- ${value}`;
  }
  if (tag === "blockquote") {
    return `> ${value}`;
  }
  return value;
}

function tableToMarkdown(table: HTMLTableElement): string {
  const rows = Array.from(table.rows)
    .slice(0, 80)
    .map((row) =>
      Array.from(row.cells)
        .slice(0, 20)
        .map((cell) =>
          isVisible(cell) && !hasSensitiveAncestor(cell)
            ? redactSensitiveText(visibleTextForElement(cell)).replaceAll("|", "\\|")
            : ""
        )
    )
    .filter((row) => row.some((cell) => cell.length > 0));
  if (rows.length === 0) {
    return "";
  }
  const width = Math.max(...rows.map((row) => row.length));
  const normalizedRows = rows.map((row) => [...row, ...Array(Math.max(0, width - row.length)).fill("")]);
  const header = normalizedRows[0];
  const separator = Array(width).fill("---");
  return [header, separator, ...normalizedRows.slice(1)].map((row) => `| ${row.join(" | ")} |`).join("\n");
}

function isAriaTableElement(element: Element): boolean {
  const role = element.getAttribute("role")?.toLowerCase() ?? "";
  return ["table", "grid", "treegrid"].includes(role);
}

function hasAncestorAriaTable(element: Element): boolean {
  for (let current = element.parentElement; current; current = current.parentElement) {
    if (isAriaTableElement(current)) {
      return true;
    }
  }
  return false;
}

function ariaTableToMarkdown(element: Element): string {
  const rows = Array.from(element.querySelectorAll("[role='row']"))
    .slice(0, 80)
    .map((row) =>
      Array.from(row.querySelectorAll("[role='columnheader'], [role='rowheader'], [role='cell'], [role='gridcell']"))
        .slice(0, 20)
        .map((cell) =>
          isVisible(cell) && !hasSensitiveAncestor(cell)
            ? redactSensitiveText(visibleTextForElement(cell)).replaceAll("|", "\\|")
            : ""
        )
    )
    .filter((row) => row.some((cell) => cell.length > 0));
  if (rows.length === 0) {
    return "";
  }
  const width = Math.max(...rows.map((row) => row.length));
  const normalizedRows = rows.map((row) => [...row, ...Array(Math.max(0, width - row.length)).fill("")]);
  const header = normalizedRows[0];
  const separator = Array(width).fill("---");
  return [header, separator, ...normalizedRows.slice(1)].map((row) => `| ${row.join(" | ")} |`).join("\n");
}

function visibleTextForElement(element: Element): string {
  const chunks: string[] = [];
  const ownerDocument = element.ownerDocument ?? document;
  const walker = ownerDocument.createTreeWalker(element, NodeFilter.SHOW_TEXT);
  while (walker.nextNode() && chunks.join("\n").length < MAX_PAGE_TEXT_CHARS) {
    const parent = walker.currentNode.parentElement;
    if (!parent || !isVisible(parent) || hasSensitiveAncestor(parent) || shouldSkipApplicationTextElement(parent)) {
      continue;
    }
    const value = normalizeText(walker.currentNode.textContent ?? "");
    if (value) {
      chunks.push(value);
    }
  }
  return chunks.join(" ").trim();
}

function hasAncestorTag(element: Element, tagName: string): boolean {
  for (let current = element.parentElement; current; current = current.parentElement) {
    if (current.tagName.toLowerCase() === tagName) {
      return true;
    }
  }
  return false;
}

function dedupeAdjacent(values: string[]): string[] {
  const result: string[] = [];
  for (const value of values) {
    if (value && value !== result[result.length - 1]) {
      result.push(value);
    }
  }
  return result;
}

function countOpenShadowRoots(root: Element): number {
  let count = 0;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_ELEMENT);
  while (walker.nextNode()) {
    if ((walker.currentNode as HTMLElement).shadowRoot) {
      count += 1;
    }
  }
  return count;
}

function siteName(): string | undefined {
  const meta = document.querySelector("meta[property='og:site_name'], meta[name='application-name']");
  const value = meta?.getAttribute("content");
  return value ? normalizeText(value) : undefined;
}

function simpleHash(value: string): string {
  let hash = 2166136261;
  for (let index = 0; index < value.length; index += 1) {
    hash ^= value.charCodeAt(index);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(16).padStart(8, "0");
}

function collectVisibleText(): string {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const chunks: string[] = [];
  let length = 0;
  while (walker.nextNode() && length < MAX_TEXT_CHARS) {
    const parent = walker.currentNode.parentElement;
    if (!parent || !isVisible(parent) || hasSensitiveAncestor(parent) || shouldSkipApplicationTextElement(parent)) {
      continue;
    }
    const value = normalizeText(walker.currentNode.textContent ?? "");
    if (value) {
      const redacted = redactSensitiveText(value);
      if (!redacted) {
        continue;
      }
      chunks.push(redacted);
      length += redacted.length + 1;
    }
  }
  const text = chunks.join("\n").slice(0, MAX_TEXT_CHARS);
  const fallback = collectApplicationTextFallback(text);
  if (fallback && text.length < 400 && fallback.text.length > text.length) {
    return fallback.text.slice(0, MAX_TEXT_CHARS);
  }
  return text;
}

function collectFullDom(
  domCaptureMode: "full" | "sanitized_selection",
  selectionSelector?: string
): ContentEvidence["fullDom"] {
  const sourceRoot =
    domCaptureMode === "sanitized_selection" && selectionSelector
      ? (document.querySelector(selectionSelector) ?? document.documentElement)
      : document.documentElement;
  const clone = sourceRoot.cloneNode(true) as HTMLElement;
  sanitizeTree(sourceRoot, clone, true);
  redactTreeText(clone);
  const html = `<!doctype html>\n${clone.outerHTML}`;
  return {
    captureMode: domCaptureMode,
    html: html.slice(0, MAX_DOM_CHARS),
    textContent: normalizeText(clone.textContent ?? "").slice(0, 250000),
    nodeCount: clone.querySelectorAll("*").length + 1,
    truncated: html.length > MAX_DOM_CHARS
  };
}

function sanitizeTree(source: Element, clone: Element, isRoot = false): boolean {
  if (!isRoot && shouldRemoveFromDom(source)) {
    clone.remove();
    return false;
  }
  sanitizeAttributes(source, clone);
  if (isSensitiveElement(source)) {
    clone.textContent = "";
    if (clone.hasAttribute("value")) {
      clone.setAttribute("value", "REDACTED");
    }
  }
  const sourceChildren = Array.from(source.children);
  const cloneChildren = Array.from(clone.children);
  for (let index = 0; index < sourceChildren.length; index += 1) {
    const childClone = cloneChildren[index];
    if (childClone) {
      sanitizeTree(sourceChildren[index], childClone, false);
    }
  }
  return true;
}

function shouldRemoveFromDom(element: Element): boolean {
  const tag = element.tagName.toLowerCase();
  if (tag === "script" || tag === "style" || tag === "noscript" || tag === "template") {
    return true;
  }
  if (tag === "meta" && isSensitiveMeta(element)) {
    return true;
  }
  if (element.hasAttribute("hidden") || element.getAttribute("aria-hidden") === "true") {
    return true;
  }
  const elementWindow = element.ownerDocument.defaultView ?? window;
  const style = elementWindow.getComputedStyle(element);
  return (
    element.hasAttribute("inert") ||
    style.display === "none" ||
    style.visibility === "hidden" ||
    style.opacity === "0" ||
    style.contentVisibility === "hidden" ||
    style.clipPath !== "none"
  );
}

function sanitizeAttributes(source: Element, clone: Element): void {
  for (const attribute of Array.from(clone.attributes)) {
    const name = attribute.name.toLowerCase();
    const originalValue = source.getAttribute(attribute.name) ?? attribute.value;
    if (name.startsWith("on") || name === "srcdoc" || name === "integrity") {
      clone.removeAttribute(attribute.name);
      continue;
    }
    if (isSensitiveAttribute(name, originalValue)) {
      clone.setAttribute(attribute.name, "REDACTED");
      continue;
    }
    if (isUrlAttribute(name)) {
      clone.setAttribute(attribute.name, sanitizedURLValue(originalValue));
    }
  }
}

function isSensitiveMeta(element: Element): boolean {
  return Array.from(element.attributes).some((attribute) => SENSITIVE_PATTERN.test(attribute.name + "=" + attribute.value));
}

function isUrlAttribute(name: string): boolean {
  return ["href", "src", "action", "formaction", "poster", "cite"].includes(name);
}

function sanitizedURLValue(value: string): string {
  try {
    const url = new URL(value, document.baseURI);
    if (url.protocol !== "http:" && url.protocol !== "https:") {
      return value;
    }
    url.search = "";
    url.hash = "";
    return url.href;
  } catch {
    return value;
  }
}

function selectionEvidence(screenRegion?: ScreenRect): ContentEvidence["selection"] & { isSensitive?: boolean } {
  const regionSelection = regionSelectionEvidence(screenRegion);
  if (regionSelection && regionSelection.text.trim().length > 0) {
    return regionSelection;
  }
  const selection = window.getSelection();
  const text = selection?.toString() ?? "";
  if (!selection || selection.rangeCount === 0) {
    return { text };
  }
  const range = selection.getRangeAt(0);
  const rect = firstNonEmptyRect(range);
  const element = elementForRange(range);
  const isSensitive = element ? hasSensitiveAncestor(element) || containsSecretValue(text) : containsSecretValue(text);
  return {
    text,
    isSensitive,
    source: "window_selection",
    confidence: text ? 0.58 : 0,
    ...(element ? { selector: selectorFor(element) } : {}),
    ...(rect ? { viewportRect: rect } : {})
  };
}

function regionSelectionEvidence(
  screenRegion?: ScreenRect
): (ContentEvidence["selection"] & { isSensitive?: boolean }) | undefined {
  const viewportRect = viewportRectForScreenRegion(screenRegion);
  if (!viewportRect) {
    return undefined;
  }
  const candidates = textNodesIntersecting(viewportRect);
  if (candidates.length === 0) {
    return { text: "", viewportRect, source: "browser_dom_region", confidence: 0.22 };
  }
  const chunks: string[] = [];
  let selector: string | undefined;
  for (const candidate of candidates) {
    if (!selector) {
      selector = selectorFor(candidate.element);
    }
    chunks.push(candidate.text);
    if (chunks.join("\n").length > 16000) {
      break;
    }
  }
  const text = dedupeAdjacent(chunks).join("\n").slice(0, 16000);
  const isSensitive = candidates.some((candidate) => hasSensitiveAncestor(candidate.element)) || containsSecretValue(text);
  const confidence = Math.min(0.94, Math.max(0.66, 0.62 + Math.min(candidates.length, 8) * 0.04));
  return {
    text,
    isSensitive,
    selector: selector ?? "dom-region",
    viewportRect,
    source: "browser_dom_region",
    confidence
  };
}

function viewportRectForScreenRegion(screenRegion?: ScreenRect): Rect | undefined {
  if (!screenRegion || screenRegion.width <= 0 || screenRegion.height <= 0) {
    return undefined;
  }
  if (screenRegion.coordinate_space === "viewport_css_px") {
    return clampViewportRect(screenRegion);
  }

  const chromeX = Math.max(0, (window.outerWidth - window.innerWidth) / 2);
  const chromeY = Math.max(0, window.outerHeight - window.innerHeight - chromeX);
  const viewportOrigin = {
    x: window.screenX + chromeX,
    y: window.screenY + chromeY
  };
  const candidates = [
    screenRegion,
    ...(window.devicePixelRatio && window.devicePixelRatio !== 1
      ? [
          {
            ...screenRegion,
            x: screenRegion.x / window.devicePixelRatio,
            y: screenRegion.y / window.devicePixelRatio,
            width: screenRegion.width / window.devicePixelRatio,
            height: screenRegion.height / window.devicePixelRatio
          }
        ]
      : [])
  ];
  let best: Rect | undefined;
  let bestArea = 0;
  for (const candidate of candidates) {
    const relative = {
      x: candidate.x - viewportOrigin.x,
      y: candidate.y - viewportOrigin.y,
      width: candidate.width,
      height: candidate.height,
      coordinate_space: "viewport_css_px" as const
    };
    const clipped = clampViewportRect(relative);
    if (!clipped) {
      continue;
    }
    const area = clipped.width * clipped.height;
    if (area > bestArea) {
      best = clipped;
      bestArea = area;
    }
  }
  return best;
}

function clampViewportRect(rect: Pick<ScreenRect, "x" | "y" | "width" | "height">): Rect | undefined {
  const left = Math.max(0, rect.x);
  const top = Math.max(0, rect.y);
  const right = Math.min(window.innerWidth, rect.x + rect.width);
  const bottom = Math.min(window.innerHeight, rect.y + rect.height);
  if (right <= left || bottom <= top) {
    return undefined;
  }
  return {
    x: left,
    y: top,
    width: right - left,
    height: bottom - top,
    coordinate_space: "viewport_css_px"
  };
}

function textNodesIntersecting(viewportRect: Rect): { element: Element; text: string }[] {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  const result: { element: Element; text: string }[] = [];
  while (walker.nextNode() && result.length < 256) {
    const node = walker.currentNode as Text;
    const parent = node.parentElement;
    if (!parent || !isVisible(parent) || hasSensitiveAncestor(parent) || shouldSkipReadableElement(parent)) {
      continue;
    }
    const text = normalizeText(node.textContent ?? "");
    if (!text) {
      continue;
    }
    const range = document.createRange();
    range.selectNodeContents(node);
    const intersects = Array.from(range.getClientRects()).some((rect) => rectIntersects(viewportRect, rect));
    range.detach();
    if (intersects) {
      result.push({ element: parent, text: redactSensitiveText(text) });
    }
  }
  return result.filter((item) => item.text.length > 0);
}

function rectIntersects(selection: Rect, candidate: DOMRect): boolean {
  return (
    candidate.right > selection.x &&
    candidate.left < selection.x + selection.width &&
    candidate.bottom > selection.y &&
    candidate.top < selection.y + selection.height
  );
}

function firstNonEmptyRect(range: Range): Rect | undefined {
  const rect = Array.from(range.getClientRects()).find((candidate) => candidate.width > 0 && candidate.height > 0);
  if (!rect) {
    return undefined;
  }
  return {
    x: rect.x,
    y: rect.y,
    width: rect.width,
    height: rect.height,
    coordinate_space: "viewport_css_px"
  };
}

function elementForRange(range: Range): Element | null {
  const container = range.commonAncestorContainer;
  return container.nodeType === Node.ELEMENT_NODE ? (container as Element) : container.parentElement;
}

function isVisible(element: Element): boolean {
  const rect = element.getBoundingClientRect();
  const elementWindow = element.ownerDocument.defaultView ?? window;
  const style = elementWindow.getComputedStyle(element);
  return (
    rect.width > 0 &&
    rect.height > 0 &&
    style.visibility !== "hidden" &&
    style.display !== "none" &&
    style.opacity !== "0" &&
    style.contentVisibility !== "hidden" &&
    style.clipPath === "none" &&
    !element.hasAttribute("inert") &&
    !hasHiddenAncestor(element)
  );
}

function hasHiddenAncestor(element: Element): boolean {
  for (let current: Element | null = element; current; current = current.parentElement) {
    if (current.getAttribute("aria-hidden") === "true" || current.hasAttribute("hidden") || current.hasAttribute("inert")) {
      return true;
    }
  }
  return false;
}

function isSensitiveControl(element: Element): boolean {
  const tag = element.tagName.toLowerCase();
  if (tag !== "input" && tag !== "textarea" && tag !== "select") {
    return false;
  }
  const type = element.getAttribute("type")?.toLowerCase();
  return type === "password" || type === "hidden" || SENSITIVE_PATTERN.test(element.outerHTML);
}

function isSensitiveElement(element: Element): boolean {
  return (
    isSensitiveControl(element) ||
    SENSITIVE_ELEMENT_HINT_PATTERN.test(element.id) ||
    SENSITIVE_ELEMENT_HINT_PATTERN.test(element.getAttribute("name") ?? "") ||
    SENSITIVE_ELEMENT_HINT_PATTERN.test(element.getAttribute("aria-label") ?? "") ||
    hasSensitiveElementAttribute(element) ||
    (element.tagName.toLowerCase() === "meta" && isSensitiveMeta(element))
  );
}

function isSensitiveAttribute(name: string, value: string): boolean {
  if (name.startsWith("data-") || STRUCTURAL_ATTRIBUTE_NAMES.has(name)) {
    return isSensitiveElementAttribute(name, value);
  }
  return SENSITIVE_PATTERN.test(name) || containsSecretValue(value);
}

function hasSensitiveElementAttribute(element: Element): boolean {
  return Array.from(element.attributes).some((attribute) =>
    isSensitiveElementAttribute(attribute.name.toLowerCase(), attribute.value)
  );
}

function isSensitiveElementAttribute(name: string, value: string): boolean {
  if (STRUCTURAL_ATTRIBUTE_NAMES.has(name)) {
    return containsSecretValue(value);
  }
  if (name.startsWith("data-")) {
    return SENSITIVE_ATTRIBUTE_NAME_PATTERN.test(name) || containsSecretValue(value);
  }
  return SENSITIVE_ATTRIBUTE_NAME_PATTERN.test(name) || containsSecretValue(value);
}

function hasSensitiveAncestor(element: Element): boolean {
  for (let current: Element | null = element; current; current = current.parentElement) {
    if (isSensitiveElement(current)) {
      return true;
    }
  }
  return false;
}

function redactTreeText(root: Element): void {
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  while (walker.nextNode()) {
    nodes.push(walker.currentNode as Text);
  }
  for (const node of nodes) {
    node.textContent = redactSensitiveText(node.textContent ?? "");
  }
}

function redactSensitiveText(value: string): string {
  let redacted = normalizeText(value);
  redacted = redacted.replace(/(authorization\s*:\s*bearer\s+)[A-Za-z0-9._~+/=-]+/gi, "$1REDACTED");
  redacted = redacted.replace(
    /((?:api[-_ ]?key|token|secret|password|credential|jwt|session|csrf|xsrf)\s*[:=]\s*)[^\s"'<>]{3,}/gi,
    "$1REDACTED"
  );
  redacted = redacted.replace(/\b(?:sk|pk)_(?:live|test)_[A-Za-z0-9_=-]{6,}\b/gi, "REDACTED");
  redacted = redacted.replace(/\bAKIA[0-9A-Z]{16}\b/g, "REDACTED");
  redacted = redacted.replace(/\b[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b/g, "REDACTED");
  if (SENSITIVE_PATTERN.test(redacted) && /[:=]\s*\S+/.test(redacted)) {
    redacted = redacted.replace(/([:=]\s*)\S+/g, "$1REDACTED");
  }
  return redacted;
}

function containsSecretValue(value: string): boolean {
  return SECRET_VALUE_PATTERNS.some((pattern) => {
    pattern.lastIndex = 0;
    return pattern.test(value);
  });
}

function selectorFor(element: Element): string {
  if (element.id) {
    return `#${CSS.escape(element.id)}`;
  }
  const parts: string[] = [];
  for (let current: Element | null = element; current && current !== document.body; current = current.parentElement) {
    parts.unshift(`${current.tagName.toLowerCase()}:nth-of-type(${nthOfType(current)})`);
    if (parts.length >= 6) {
      break;
    }
  }
  return parts.join(" > ") || element.tagName.toLowerCase();
}

function nthOfType(element: Element): number {
  let index = 1;
  for (let sibling = element.previousElementSibling; sibling; sibling = sibling.previousElementSibling) {
    if (sibling.tagName === element.tagName) {
      index += 1;
    }
  }
  return index;
}

function normalizeText(value: string): string {
  return value.replace(/\s+/g, " ").trim();
}
