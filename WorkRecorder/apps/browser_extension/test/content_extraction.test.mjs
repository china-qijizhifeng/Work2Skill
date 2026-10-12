import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import vm from "node:vm";
import { JSDOM } from "jsdom";

const ROOT = path.resolve(import.meta.dirname, "..");
const CONTENT_SCRIPT = fs.readFileSync(path.join(ROOT, "dist", "content.js"), "utf8");

test("extracts div-only SPA text without semantic paragraph tags", () => {
  const evidence = collect(
    "<main role='main'><div><div>DIV_ONLY_SPA_UNIQUE_CONTEXT lives in app-rendered divs.</div></div></main>"
  );

  assert.match(evidence.pageText.plainText, /DIV_ONLY_SPA_UNIQUE_CONTEXT/);
  assert.match(evidence.pageText.method, /inner_text_fallback/);
  assert.match(evidence.visibleText, /DIV_ONLY_SPA_UNIQUE_CONTEXT/);
});

test("does not treat token-named CSS classes as sensitive subtrees", () => {
  const evidence = collect(
    "<main><section class='text-token-text-primary'><div>SPA_TOKEN_CLASS_UNIQUE_CONTEXT remains readable.</div></section></main>"
  );

  assert.match(evidence.pageText.plainText, /SPA_TOKEN_CLASS_UNIQUE_CONTEXT/);
  assert.doesNotMatch(evidence.pageText.plainText, /SHOULD_NOT_LEAK/);
});

test("fallback does not leak hidden, navigation, or sensitive descendant text", () => {
  const evidence = collect(
    "<nav><div>SHOULD_NOT_LEAK_NAV_FALLBACK</div></nav>" +
      "<main>" +
      "<section data-auth-token='SHOULD_NOT_LEAK_AUTH_ZONE'><div>SHOULD_NOT_LEAK_AUTH_ZONE</div></section>" +
      "<div hidden>SHOULD_NOT_LEAK_HIDDEN_FALLBACK</div>" +
      "<div style='display:none'>SHOULD_NOT_LEAK_DISPLAY_NONE</div>" +
      "<div>VISIBLE_FALLBACK_CONTEXT_UNIQUE remains readable.</div>" +
      "</main>"
  );

  assert.match(evidence.pageText.plainText, /VISIBLE_FALLBACK_CONTEXT_UNIQUE/);
  assert.doesNotMatch(evidence.pageText.plainText, /SHOULD_NOT_LEAK/);
  assert.doesNotMatch(evidence.visibleText, /SHOULD_NOT_LEAK/);
});

test("extracts ARIA grid dashboards as markdown table source text", () => {
  const evidence = collect(
    "<main><div role='grid'>" +
      "<div role='row'><span role='columnheader'>Account</span><span role='columnheader'>Risk</span></div>" +
      "<div role='row'><span role='gridcell'>ACME</span><span role='gridcell'>ARIA_GRID_RENEWAL_RISK_UNIQUE</span></div>" +
      "</div></main>"
  );

  assert.match(evidence.pageText.markdown, /\| Account \| Risk \|/);
  assert.match(evidence.pageText.markdown, /ARIA_GRID_RENEWAL_RISK_UNIQUE/);
});

function collect(bodyHtml) {
  const dom = new JSDOM(
    "<!doctype html><html lang='zh-CN'><head><title>WorkRecorder Test</title></head><body>" +
      bodyHtml +
      "</body></html>",
    { url: "https://example.test/page" }
  );
  installVisibilityMocks(dom);

  let listener;
  const sandbox = {
    window: dom.window,
    document: dom.window.document,
    Node: dom.window.Node,
    NodeFilter: dom.window.NodeFilter,
    Element: dom.window.Element,
    HTMLElement: dom.window.HTMLElement,
    HTMLIFrameElement: dom.window.HTMLIFrameElement,
    HTMLTableElement: dom.window.HTMLTableElement,
    Text: dom.window.Text,
    Range: dom.window.Range,
    CSS: dom.window.CSS,
    URL: dom.window.URL,
    crypto: { randomUUID: () => "00000000-0000-4000-8000-000000000000" },
    console,
    chrome: {
      runtime: {
        onMessage: {
          addListener(callback) {
            listener = callback;
          }
        },
        sendMessage() {
          return Promise.resolve();
        }
      }
    }
  };

  vm.createContext(sandbox);
  vm.runInContext(CONTENT_SCRIPT, sandbox, { filename: "content.js" });
  assert.equal(typeof listener, "function");

  let response;
  listener({ type: "workrecorder.collectEvidence", domCaptureMode: "full" }, {}, (value) => {
    response = value;
  });
  assert.ok(response);
  return response;
}

function installVisibilityMocks(dom) {
  Object.defineProperty(dom.window.HTMLElement.prototype, "innerText", {
    configurable: true,
    get() {
      return visibleText(this);
    }
  });
  dom.window.Element.prototype.getBoundingClientRect = function getBoundingClientRect() {
    return { x: 0, y: 0, left: 0, top: 0, right: 640, bottom: 32, width: 640, height: 32 };
  };
  dom.window.getComputedStyle = (element) => {
    const style = element.getAttribute("style") ?? "";
    return {
      visibility: /visibility\s*:\s*hidden/i.test(style) ? "hidden" : "visible",
      display: /display\s*:\s*none/i.test(style) ? "none" : "block",
      opacity: /opacity\s*:\s*0/i.test(style) ? "0" : "1",
      contentVisibility: /content-visibility\s*:\s*hidden/i.test(style) ? "hidden" : "visible",
      clipPath: "none"
    };
  };
}

function visibleText(element) {
  const walker = element.ownerDocument.createTreeWalker(element, domNodeFilter(element.ownerDocument).SHOW_TEXT);
  const chunks = [];
  while (walker.nextNode()) {
    const parent = walker.currentNode.parentElement;
    if (parent && !isHidden(parent)) {
      const text = walker.currentNode.textContent?.replace(/\s+/g, " ").trim();
      if (text) {
        chunks.push(text);
      }
    }
  }
  return chunks.join("\n");
}

function isHidden(element) {
  for (let current = element; current; current = current.parentElement) {
    const style = current.getAttribute("style") ?? "";
    if (
      current.hasAttribute("hidden") ||
      current.getAttribute("aria-hidden") === "true" ||
      /display\s*:\s*none/i.test(style) ||
      /visibility\s*:\s*hidden/i.test(style)
    ) {
      return true;
    }
  }
  return false;
}

function domNodeFilter(document) {
  return document.defaultView.NodeFilter;
}
