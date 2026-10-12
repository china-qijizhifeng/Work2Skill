const motionQuery = window.matchMedia("(prefers-reduced-motion: reduce)");
let prefersReducedMotion = motionQuery.matches;
const motionCallbacks = new Set<(reduced: boolean) => void>();

motionQuery.addEventListener("change", (event) => {
  prefersReducedMotion = event.matches;
  motionCallbacks.forEach((callback) => callback(prefersReducedMotion));
});

const menuToggle = document.querySelector<HTMLButtonElement>("[data-menu-toggle]");
if (menuToggle) {
  const setMenuOpen = (isOpen: boolean) => {
    document.body.classList.toggle("menu-open", isOpen);
    menuToggle.setAttribute("aria-expanded", String(isOpen));
    menuToggle.setAttribute("aria-label", isOpen ? "关闭导航" : "打开导航");
  };
  menuToggle.addEventListener("click", () => {
    setMenuOpen(!document.body.classList.contains("menu-open"));
  });
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") setMenuOpen(false);
  });
  document.addEventListener("click", (event) => {
    if (!(event.target instanceof Node)) return;
    if (menuToggle.contains(event.target) || document.querySelector("[data-nav-links]")?.contains(event.target)) return;
    setMenuOpen(false);
  });
}

document.querySelectorAll<HTMLAnchorElement>("[data-nav-links] a").forEach((link) => {
  link.addEventListener("click", () => {
    document.body.classList.remove("menu-open");
    menuToggle?.setAttribute("aria-expanded", "false");
    menuToggle?.setAttribute("aria-label", "打开导航");
  });
});

const scrollToHashTarget = () => {
  if (!window.location.hash) return;
  const targetId = decodeURIComponent(window.location.hash.slice(1));
  const target = document.getElementById(targetId);
  if (!target) return;
  const align = () => target.scrollIntoView({ block: "start" });
  window.requestAnimationFrame(align);
  window.setTimeout(align, 90);
  window.setTimeout(align, 320);
};

window.addEventListener("load", scrollToHashTarget);
window.addEventListener("hashchange", scrollToHashTarget);

const revealElements = Array.from(document.querySelectorAll<HTMLElement>(".reveal"));
if (prefersReducedMotion || !("IntersectionObserver" in window)) {
  revealElements.forEach((element) => element.classList.add("reduced-motion"));
} else {
  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (!entry.isIntersecting) return;
        entry.target.classList.add("in-view");
        observer.unobserve(entry.target);
      });
    },
    { rootMargin: "0px 0px -10% 0px", threshold: 0.18 }
  );
  revealElements.forEach((element) => observer.observe(element));
}
motionCallbacks.add((reduced) => {
  if (reduced) revealElements.forEach((element) => element.classList.add("reduced-motion"));
});

const runWhenVisible = (root: HTMLElement, start: () => void, stop?: () => void, threshold = 0.24) => {
  if (prefersReducedMotion || !("IntersectionObserver" in window)) {
    start();
    return;
  }
  let running = false;
  const observer = new IntersectionObserver(
    (entries) => {
      const isVisible = entries.some((entry) => entry.isIntersecting);
      if (isVisible && !running) {
        running = true;
        start();
        return;
      }
      if (!isVisible && running) {
        running = false;
        stop?.();
      }
    },
    { threshold }
  );
  observer.observe(root);
};

let tabGroupIndex = 0;
document.querySelectorAll<HTMLElement>("[data-tabs]").forEach((root) => {
  const groupId = `workrecorder-tabs-${tabGroupIndex}`;
  tabGroupIndex += 1;
  const tabs = Array.from(root.querySelectorAll<HTMLButtonElement>("[data-tab]"));
  const panels = Array.from(root.querySelectorAll<HTMLElement>("[data-panel]"));
  const activate = (key: string) => {
    root.dataset.active = key;
    root.classList.remove("is-switching", "is-stage-playing");
    void root.offsetWidth;
    root.classList.add("is-switching");
    if (root.hasAttribute("data-architecture-flow")) root.classList.add("is-stage-playing");
    tabs.forEach((tab) => {
      const active = tab.dataset.tab === key;
      tab.classList.toggle("active", active);
      tab.setAttribute("aria-selected", String(active));
      tab.setAttribute("tabindex", active ? "0" : "-1");
    });
    panels.forEach((panel) => {
      const active = panel.dataset.panel === key;
      panel.classList.toggle("active", active);
      panel.hidden = !active;
    });
  };
  tabs.forEach((tab, index) => {
    const key = tab.dataset.tab ?? String(index);
    tab.id ||= `${groupId}-tab-${key}`;
    tab.setAttribute("tabindex", tab.classList.contains("active") || tab.getAttribute("aria-selected") === "true" ? "0" : "-1");
    const matchingPanels = panels.filter((item) => item.dataset.panel === key);
    matchingPanels.forEach((panel, panelIndex) => {
      panel.id ||= `${groupId}-panel-${key}-${panelIndex}`;
      if (panelIndex === 0) tab.setAttribute("aria-controls", panel.id);
      panel.setAttribute("aria-labelledby", tab.id);
      panel.hidden = !(panel.classList.contains("active") || tab.getAttribute("aria-selected") === "true");
    });
    tab.addEventListener("click", () => activate(key));
    tab.addEventListener("keydown", (event) => {
      const currentIndex = tabs.indexOf(tab);
      let nextIndex: number | null = null;
      if (event.key === "ArrowRight" || event.key === "ArrowDown") nextIndex = (currentIndex + 1) % tabs.length;
      if (event.key === "ArrowLeft" || event.key === "ArrowUp") nextIndex = (currentIndex - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") nextIndex = 0;
      if (event.key === "End") nextIndex = tabs.length - 1;
      if (nextIndex === null) return;
      event.preventDefault();
      tabs[nextIndex]?.focus();
      activate(tabs[nextIndex]?.dataset.tab ?? "");
    });
  });
  const autoTabsMs = Number(root.dataset.autoTabs ?? "0");
  if (autoTabsMs > 0 && tabs.length > 1) {
    let autoIndex = Math.max(0, tabs.findIndex((tab) => tab.classList.contains("active")));
    let timer = 0;
    const stop = () => {
      if (timer) window.clearInterval(timer);
      timer = 0;
    };
    const start = () => {
      stop();
      if (prefersReducedMotion) return;
      timer = window.setInterval(() => {
        if (root.matches(":hover") || document.visibilityState !== "visible") return;
        autoIndex = (autoIndex + 1) % tabs.length;
        activate(tabs[autoIndex]?.dataset.tab ?? "");
      }, autoTabsMs);
    };
    tabs.forEach((tab, tabIndex) => {
      tab.addEventListener("click", () => {
        autoIndex = tabIndex;
        stop();
      });
    });
    runWhenVisible(root, start, stop);
    motionCallbacks.add((reduced) => {
      if (reduced) stop();
      else start();
    });
  }
});

document.querySelectorAll<HTMLElement>("[data-evidence-demo]").forEach((root) => {
  const linked = Array.from(root.querySelectorAll<HTMLElement>("[data-evidence]"));
  const replay = root.querySelector<HTMLButtonElement>("[data-evidence-replay]");
  const sequence = Array.from(new Set(linked.map((element) => element.dataset.evidence).filter(Boolean))) as string[];
  const timers: number[] = [];
  let loop = 0;
  let index = 0;
  const clearTimers = () => {
    while (timers.length > 0) window.clearTimeout(timers.pop());
  };
  const clearLoop = () => {
    if (loop) window.clearInterval(loop);
    loop = 0;
  };
  const setActive = (key: string) => {
    root.dataset.evidenceActive = key;
    linked.forEach((element) => {
      const active = element.dataset.evidence === key;
      element.classList.toggle("active", active);
      element.classList.toggle("is-evidence-active", active);
      if (element instanceof HTMLButtonElement) {
        element.setAttribute("aria-pressed", String(active));
      }
    });
  };
  const advance = () => {
    if (prefersReducedMotion || document.visibilityState !== "visible") return;
    setActive(sequence[index % sequence.length]);
    index += 1;
  };
  const playSequence = () => {
    clearTimers();
    index = 0;
    root.classList.remove("is-evidence-complete");
    root.classList.add("is-acme-sequencing");
    sequence.forEach((key, stepIndex) => {
      timers.push(window.setTimeout(() => setActive(key), stepIndex * 1050));
    });
    timers.push(window.setTimeout(() => {
      root.classList.remove("is-acme-sequencing");
      root.classList.add("is-evidence-complete");
    }, sequence.length * 1050 + 240));
  };
  linked.forEach((element) => {
    element.addEventListener("pointerenter", () => {
      clearTimers();
      root.classList.remove("is-acme-sequencing");
      setActive(element.dataset.evidence ?? "pricing");
    });
    element.addEventListener("focus", () => setActive(element.dataset.evidence ?? "pricing"));
    element.addEventListener("click", () => setActive(element.dataset.evidence ?? "pricing"));
  });
  replay?.addEventListener("click", () => {
    if (prefersReducedMotion) {
      clearTimers();
      clearLoop();
      setActive("pricing");
      root.classList.remove("is-acme-sequencing");
      root.classList.add("is-evidence-complete");
      return;
    }
    playSequence();
  });
  const startEvidenceLoop = () => {
    if (prefersReducedMotion) return;
    playSequence();
    loop = window.setInterval(() => {
      if (!root.matches(":hover")) advance();
    }, 2400);
  };
  runWhenVisible(root, startEvidenceLoop, () => {
    clearTimers();
    clearLoop();
  });
  motionCallbacks.add((reduced) => {
    clearTimers();
    clearLoop();
    root.classList.remove("is-acme-sequencing");
    if (reduced) {
      setActive("pricing");
      root.classList.add("is-evidence-complete");
      return;
    }
    startEvidenceLoop();
  });
});

document.querySelectorAll<HTMLElement>("[data-home-proof-demo]").forEach((root) => {
  const linked = Array.from(root.querySelectorAll<HTMLElement>("[data-proof-step]"));
  const sequence = ["scattered", "weak", "evidence"];
  let index = 0;
  let interval = 0;
  const setActive = (key: string) => {
    root.dataset.proofCurrent = key;
    linked.forEach((element) => element.classList.toggle("active", element.dataset.proofStep === key));
  };
  const stop = () => {
    if (interval) window.clearInterval(interval);
    interval = 0;
  };
  const start = () => {
    stop();
    if (prefersReducedMotion) return;
    interval = window.setInterval(() => {
      setActive(sequence[index % sequence.length]);
      index += 1;
    }, 2100);
  };
  linked.forEach((element) => {
    element.addEventListener("pointerenter", () => {
      stop();
      setActive(element.dataset.proofStep ?? "scattered");
    });
    element.addEventListener("focus", () => setActive(element.dataset.proofStep ?? "scattered"));
  });
  root.addEventListener("pointerleave", start);
  runWhenVisible(root, start, stop);
  motionCallbacks.add((reduced) => {
    if (reduced) {
      stop();
      setActive("scattered");
      return;
    }
    start();
  });
});

document.querySelectorAll<HTMLElement>("[data-capture-simulator]").forEach((root) => {
  const canvas = root.querySelector<HTMLElement>("[data-capture-canvas]");
  const selection = root.querySelector<HTMLElement>("[data-capture-selection]");
  const selectionTags = root.querySelector<HTMLElement>(".sim-selection-tags");
  const resultCard = root.querySelector<HTMLElement>("[data-capture-result-card]");
  const note = root.querySelector<HTMLElement>("[data-capture-note]");
  const noteInput = root.querySelector<HTMLTextAreaElement>("[data-capture-note-input]");
  const cursor = root.querySelector<HTMLElement>("[data-capture-cursor]");
  const replay = root.querySelector<HTMLButtonElement>("[data-capture-replay]");
  const steps = Array.from(root.querySelectorAll<HTMLElement>("[data-capture-step]"));
  const resultTitle = root.querySelector<HTMLElement>("[data-capture-result-title]");
  const resultBody = root.querySelector<HTMLElement>("[data-capture-result-body]");
  const eventKicker = root.querySelector<HTMLElement>("[data-capture-event-kicker]");
  const eventTitle = root.querySelector<HTMLElement>("[data-capture-event-title]");
  const eventBody = root.querySelector<HTMLElement>("[data-capture-event-body]");
  if (!canvas || !selection || !note) return;

  const timers: number[] = [];
  let dragFrame = 0;
  let dragging = false;
  let startX = 0;
  let startY = 0;
  let lastX = 0;
  let lastY = 0;
  let lastSelection = { x: 0, y: 0, width: 0, height: 0 };
  let cursorFadeTimer = 0;
  const targetRatio = { left: 0.43, top: 0.23, width: 0.43, height: 0.34 };

  const clearTimers = () => {
    while (timers.length > 0) window.clearTimeout(timers.pop());
    if (cursorFadeTimer) window.clearTimeout(cursorFadeTimer);
    cursorFadeTimer = 0;
  };
  const clearDragFrame = () => {
    if (dragFrame) window.cancelAnimationFrame(dragFrame);
    dragFrame = 0;
  };
  const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));
  const setStep = (key: string) => {
    root.dataset.capturePhase = key;
    steps.forEach((step) => step.classList.toggle("active", step.dataset.captureStep === key));
  };
  const positionNote = (rect: DOMRect | { x: number; y: number; width: number; height: number }) => {
    const maxWidth = Math.min(note.offsetWidth || 430, canvas.clientWidth - 24);
    const noteHeight = note.offsetHeight || 132;
    const left = clamp(rect.x, 12, Math.max(12, canvas.clientWidth - maxWidth - 12));
    let top = rect.y + rect.height + 14;
    if (top + noteHeight > canvas.clientHeight - 12) top = rect.y - noteHeight - 14;
    note.style.left = `${left}px`;
    note.style.top = `${clamp(top, 12, Math.max(12, canvas.clientHeight - noteHeight - 12))}px`;
  };
  const setRect = (x: number, y: number, width: number, height: number) => {
    const minX = 10;
    const minY = 10;
    const maxX = Math.max(minX + 20, canvas.clientWidth - 10);
    const maxY = Math.max(minY + 20, canvas.clientHeight - 10);
    const x1 = clamp(x, minX, maxX);
    const y1 = clamp(y, minY, maxY);
    const x2 = clamp(x + width, minX, maxX);
    const y2 = clamp(y + height, minY, maxY);
    const normalized = {
      x: Math.min(x1, x2),
      y: Math.min(y1, y2),
      width: Math.max(20, Math.abs(x2 - x1)),
      height: Math.max(20, Math.abs(y2 - y1))
    };
    lastSelection = normalized;
    selection.style.left = `${normalized.x}px`;
    selection.style.top = `${normalized.y}px`;
    selection.style.width = `${normalized.width}px`;
    selection.style.height = `${normalized.height}px`;
    selection.style.opacity = "1";
    if (selectionTags) {
      selectionTags.style.left = `${normalized.x}px`;
      selectionTags.style.top = `${Math.max(12, normalized.y - 38)}px`;
    }
    if (resultCard) {
      resultCard.style.left = `${clamp(normalized.x + normalized.width - resultCard.offsetWidth, 12, Math.max(12, canvas.clientWidth - resultCard.offsetWidth - 12))}px`;
      resultCard.style.top = `${clamp(normalized.y + normalized.height + 14, 12, Math.max(12, canvas.clientHeight - resultCard.offsetHeight - 12))}px`;
    }
    positionNote(normalized);
  };
  const setRatioRect = (ratio = targetRatio) => {
    setRect(
      canvas.clientWidth * ratio.left,
      canvas.clientHeight * ratio.top,
      canvas.clientWidth * ratio.width,
      canvas.clientHeight * ratio.height
    );
  };
  const setCursor = (x: number, y: number, opacity = 1) => {
    if (!cursor) return;
    cursor.style.left = `${x}px`;
    cursor.style.top = `${y}px`;
    cursor.style.opacity = String(opacity);
  };
  const hideSelection = () => {
    selection.style.opacity = "0";
    selection.style.left = `${canvas.clientWidth * targetRatio.left}px`;
    selection.style.top = `${canvas.clientHeight * targetRatio.top}px`;
    selection.style.width = "0px";
    selection.style.height = "0px";
    positionNote({
      x: canvas.clientWidth * targetRatio.left,
      y: canvas.clientHeight * targetRatio.top,
      width: 0,
      height: 0
    });
  };
  const animateDrag = () => {
    clearDragFrame();
    const start = {
      x: canvas.clientWidth * targetRatio.left,
      y: canvas.clientHeight * targetRatio.top
    };
    const end = {
      x: canvas.clientWidth * (targetRatio.left + targetRatio.width),
      y: canvas.clientHeight * (targetRatio.top + targetRatio.height)
    };
    const startedAt = performance.now();
    const tick = (now: number) => {
      const linear = clamp((now - startedAt) / 1160, 0, 1);
      const eased = 1 - Math.pow(1 - linear, 3);
      const x = start.x + (end.x - start.x) * eased;
      const y = start.y + (end.y - start.y) * eased;
      setCursor(x, y, linear < 0.08 ? linear / 0.08 : 1);
      setRect(start.x, start.y, Math.max(20, x - start.x), Math.max(20, y - start.y));
      if (linear < 1) dragFrame = window.requestAnimationFrame(tick);
    };
    dragFrame = window.requestAnimationFrame(tick);
  };

  const selectedAreaLabel = () => {
    const centerX = lastSelection.x + lastSelection.width / 2;
    const centerY = lastSelection.y + lastSelection.height / 2;
    const widthRatio = lastSelection.width / Math.max(canvas.clientWidth, 1);
    if (widthRatio > 0.62) return "整页风险概览";
    if (centerY < canvas.clientHeight * 0.42) return centerX < canvas.clientWidth * 0.58 ? "续约金额 KPI" : "预算偏差 KPI";
    if (centerX > canvas.clientWidth * 0.48) return "报价风险表格";
    return "ACME 侧栏信息";
  };

  const updateSavedCopy = () => {
    const area = selectedAreaLabel();
    const rawNote = noteInput?.value.trim() || "用于 ACME 下周续约会议 briefing";
    const shortNote = rawNote.length > 42 ? `${rawNote.slice(0, 42)}…` : rawNote;
    const title = area === "ACME 侧栏信息" ? "ACME 续约现场备注" : `ACME ${area}`;
    resultTitle && (resultTitle.textContent = title);
    resultBody && (resultBody.textContent = `备注「${shortNote}」已和 ${area}、App、时间、识别文字、截图引用一起保存；完整原图仍需确认打开。`);
    eventKicker && (eventKicker.textContent = area);
    eventTitle && (eventTitle.textContent = "证据卡已生成");
    eventBody && (eventBody.textContent = `这条记录会按「${shortNote}」进入工作台；搜索先看到短卡，需要时再点开记录。`);
  };

  const play = () => {
    clearTimers();
    clearDragFrame();
    root.classList.remove("is-playing");
    void root.offsetWidth;
    root.classList.add("is-playing");
    root.classList.add("is-dragging");
    setStep("drag");
    setRatioRect({ ...targetRatio, width: 0.04, height: 0.04 });
    if (prefersReducedMotion) {
      setRatioRect();
      setStep("save");
      root.classList.remove("is-dragging");
      return;
    }
    animateDrag();
    const schedule = [
      ["note", 1280],
      ["save", 2300]
    ] as const;
    schedule.forEach(([key, delay]) => {
      timers.push(
        window.setTimeout(() => {
          setStep(key);
          if (key === "save") updateSavedCopy();
          if (key === "note") root.classList.remove("is-dragging");
        }, delay)
      );
    });
  };

  canvas.addEventListener("pointerdown", (event) => {
    clearTimers();
    clearDragFrame();
    const bounds = canvas.getBoundingClientRect();
    dragging = true;
    root.classList.remove("is-playing");
    root.classList.add("is-dragging");
    setStep("drag");
    startX = event.clientX - bounds.left;
    startY = event.clientY - bounds.top;
    lastX = startX;
    lastY = startY;
    setCursor(startX, startY, 1);
    selection.style.opacity = "1";
    setRect(startX, startY, 20, 20);
    canvas.setPointerCapture(event.pointerId);
  });
  note.addEventListener("pointerdown", (event) => event.stopPropagation());
  canvas.addEventListener("pointermove", (event) => {
    if (!dragging) return;
    const bounds = canvas.getBoundingClientRect();
    const currentX = event.clientX - bounds.left;
    const currentY = event.clientY - bounds.top;
    lastX = currentX;
    lastY = currentY;
    setCursor(currentX, currentY, 1);
    setRect(Math.min(startX, currentX), Math.min(startY, currentY), Math.abs(currentX - startX), Math.abs(currentY - startY));
  });
  const endDrag = (event: PointerEvent) => {
    if (!dragging) return;
    dragging = false;
    root.classList.remove("is-dragging");
    setStep("note");
    setCursor(lastX, lastY, 1);
    cursorFadeTimer = window.setTimeout(() => setCursor(lastX, lastY, 0), 900);
    if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId);
  };
  canvas.addEventListener("pointerup", endDrag);
  canvas.addEventListener("pointercancel", endDrag);

  hideSelection();
  if ("ResizeObserver" in window) {
    const resizeObserver = new ResizeObserver(() => {
      if (dragging) return;
      window.requestAnimationFrame(() => {
        if (root.dataset.capturePhase === "drag" && !root.classList.contains("is-playing")) hideSelection();
        else setRatioRect();
      });
    });
    resizeObserver.observe(canvas);
  }
  window.addEventListener("load", () => {
    if (!dragging) hideSelection();
  });
  replay?.addEventListener("click", play);
  root.querySelector<HTMLButtonElement>("[data-capture-save]")?.addEventListener("click", () => {
    clearTimers();
    root.classList.remove("is-dragging");
    updateSavedCopy();
    setStep("save");
  });
  runWhenVisible(root, () => {
    if (!prefersReducedMotion) timers.push(window.setTimeout(play, 260));
  }, () => {
    clearTimers();
    clearDragFrame();
  });
});

document.querySelectorAll<HTMLElement>("[data-hero-demo]").forEach((workbenchDemo) => {
  const cards = Array.from(workbenchDemo.querySelectorAll<HTMLElement>("[data-demo-card]"));
  const pauseButton = workbenchDemo.querySelector<HTMLButtonElement>("[data-hero-demo-pause]");
  let cardIndex = 0;
  let autoplay = !prefersReducedMotion;
  let hoverPaused = false;
  const setPauseButton = () => {
    if (!pauseButton) return;
    if (prefersReducedMotion) {
      pauseButton.textContent = "动画已关闭";
      pauseButton.disabled = true;
      return;
    }
    pauseButton.disabled = false;
    pauseButton.textContent = autoplay ? "暂停" : "继续";
    pauseButton.setAttribute("aria-pressed", String(!autoplay));
  };
  pauseButton?.addEventListener("click", () => {
    autoplay = !autoplay;
    setPauseButton();
  });
  workbenchDemo.addEventListener("pointerenter", () => {
    hoverPaused = true;
  });
  workbenchDemo.addEventListener("pointerleave", () => {
    hoverPaused = false;
  });
  workbenchDemo.addEventListener("focusin", (event) => {
    if (event.target === pauseButton) return;
    autoplay = false;
    setPauseButton();
  });
  setPauseButton();
  motionCallbacks.add((reduced) => {
    autoplay = !reduced;
    setPauseButton();
  });
  window.setInterval(() => {
    if (!autoplay || hoverPaused) return;
    cards.forEach((card, index) => card.classList.toggle("active", index === cardIndex));
    cardIndex = (cardIndex + 1) % cards.length;
  }, 2400);
});

document.querySelectorAll<HTMLElement>("[data-recording-cinema]").forEach((root) => {
  const steps = Array.from(root.querySelectorAll<HTMLButtonElement>(".cinema-step[data-cinema-step]"));
  const confirmButtons = Array.from(root.querySelectorAll<HTMLButtonElement>("[data-cinema-confirm-step]"));
  const panes = Array.from(root.querySelectorAll<HTMLElement>("[data-cinema-pane]"));
  const flowItems = Array.from(root.querySelectorAll<HTMLElement>("[data-cinema-flow]"));
  if (steps.length === 0 || panes.length === 0) return;
  let index = 0;
  let timer = 0;
  const autoplayStates = Math.min(3, steps.length);
  const setActive = (nextIndex: number) => {
    index = nextIndex;
    root.dataset.cinemaState = String(nextIndex);
    steps.forEach((step, stepIndex) => {
      const active = stepIndex === nextIndex;
      step.classList.toggle("active", active);
      step.setAttribute("aria-pressed", String(active));
    });
    panes.forEach((pane, paneIndex) => {
      const active = paneIndex === nextIndex;
      pane.classList.toggle("active", active);
      pane.setAttribute("aria-current", String(active));
    });
    flowItems.forEach((item) => {
      const itemIndex = Number(item.dataset.cinemaFlow ?? "-1");
      item.classList.toggle("active", itemIndex === nextIndex);
    });
  };
  const stop = () => {
    if (timer) window.clearInterval(timer);
    timer = 0;
  };
  const start = () => {
    stop();
    if (prefersReducedMotion) return;
    timer = window.setInterval(() => {
      if (root.matches(":hover") || document.visibilityState !== "visible") return;
      setActive((index + 1) % autoplayStates);
    }, 2400);
  };
  steps.forEach((step, stepIndex) => {
    step.addEventListener("click", () => {
      stop();
      setActive(stepIndex);
    });
    step.addEventListener("focus", () => setActive(stepIndex));
  });
  confirmButtons.forEach((button) => {
    const target = Number(button.dataset.cinemaConfirmStep ?? "3");
    button.addEventListener("click", () => {
      stop();
      setActive(Number.isFinite(target) ? target : 3);
    });
    button.addEventListener("focus", () => setActive(2));
  });
  setActive(0);
  runWhenVisible(root, start, stop);
  motionCallbacks.add((reduced) => {
    if (reduced) {
      stop();
      setActive(0);
      return;
    }
    start();
  });
});

document.querySelectorAll<HTMLElement>("[data-agent-demo]").forEach((root) => {
  const stages = Array.from(root.querySelectorAll<HTMLElement>("[data-agent-stage]"));
  const actions = Array.from(root.querySelectorAll<HTMLElement>("[data-agent-action]"));
  const cards = Array.from(root.querySelectorAll<HTMLElement>("[data-agent-stage-card]"));
  const pipe = Array.from(root.querySelectorAll<HTMLElement>("[data-agent-pipe]"));
  if (stages.length === 0) return;
  let index = 0;
  let timer = 0;
  const setActive = (nextIndex: number) => {
    index = nextIndex;
    stages.forEach((stage, stageIndex) => stage.classList.toggle("active", stageIndex === nextIndex));
    actions.forEach((action, actionIndex) => action.classList.toggle("active", actionIndex === nextIndex));
    pipe.forEach((item, itemIndex) => item.classList.toggle("active", itemIndex <= nextIndex));
    cards.forEach((card, cardIndex) => {
      const active = nextIndex < 2 ? cardIndex === nextIndex : true;
      card.classList.toggle("active", active);
    });
  };
  const stop = () => {
    if (timer) window.clearInterval(timer);
    timer = 0;
  };
  const start = () => {
    stop();
    if (prefersReducedMotion) return;
    timer = window.setInterval(() => {
      if (root.matches(":hover") || document.visibilityState !== "visible") return;
      setActive((index + 1) % stages.length);
    }, 2200);
  };
  stages.forEach((stage, stageIndex) => {
    stage.setAttribute("tabindex", "0");
    stage.addEventListener("pointerenter", () => setActive(stageIndex));
    stage.addEventListener("focusin", () => setActive(stageIndex));
  });
  setActive(0);
  runWhenVisible(root, start, stop);
  motionCallbacks.add((reduced) => {
    if (reduced) {
      stop();
      setActive(0);
      return;
    }
    start();
  });
});

document.querySelectorAll<HTMLElement>("[data-agent-trace]").forEach((root) => {
  const steps = Array.from(root.querySelectorAll<HTMLButtonElement>("[data-trace-step]"));
  const panels = Array.from(root.querySelectorAll<HTMLElement>("[data-trace-panel]"));
  const activate = (index: number) => {
    steps.forEach((step, stepIndex) => {
      const active = stepIndex === index;
      step.classList.toggle("active", active);
      step.setAttribute("aria-selected", String(active));
    });
    panels.forEach((panel, panelIndex) => {
      panel.classList.toggle("active", panelIndex === index);
    });
  };
  steps.forEach((step, index) => {
    step.addEventListener("click", () => activate(index));
  });
});
