(function () {
  const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const clearTimerList = (timers) => {
    while (timers.length) window.clearTimeout(timers.pop());
  };

  const playWhenVisible = (root, play, threshold = 0.38) => {
    let played = false;
    if (reduceMotion) {
      play(true);
      return;
    }
    if ("IntersectionObserver" in window) {
      const observer = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting && !played) {
              played = true;
              play(false);
              observer.unobserve(root);
            }
          });
        },
        { threshold }
      );
      observer.observe(root);
    } else {
      play(false);
    }
  };

  const toggle = document.querySelector("[data-menu-toggle]");
  if (toggle) {
    toggle.addEventListener("click", () => {
      const open = document.body.classList.toggle("menu-open");
      toggle.setAttribute("aria-expanded", String(open));
    });
  }

  document.querySelectorAll(".nav-links a").forEach((link) => {
    link.addEventListener("click", () => {
      document.body.classList.remove("menu-open");
      if (toggle) toggle.setAttribute("aria-expanded", "false");
    });
  });

  document.querySelectorAll("[data-tabs]").forEach((root) => {
    const buttons = Array.from(root.querySelectorAll("[data-tab]"));
    const panels = Array.from(root.querySelectorAll("[data-panel]"));
    buttons.forEach((button) => {
      button.addEventListener("click", () => {
        const target = button.dataset.tab;
        root.dataset.active = target;
        root.classList.remove("is-switching");
        void root.offsetWidth;
        root.classList.add("is-switching");
        buttons.forEach((item) => {
          item.setAttribute("aria-selected", String(item === button));
          item.classList.toggle("active", item === button);
        });
        panels.forEach((panel) => {
          panel.classList.toggle("active", panel.dataset.panel === target);
        });
      });
    });
  });

  document.querySelectorAll("[data-evidence-demo]").forEach((root) => {
    const linked = Array.from(root.querySelectorAll("[data-evidence]"));
    const replay = root.querySelector("[data-evidence-replay]");
    const sequence = ["pricing", "chat", "crm", "mail"];
    const timers = [];
    const setActive = (key) => {
      linked.forEach((item) => {
        item.classList.toggle("is-evidence-active", item.dataset.evidence === key);
      });
      root.dataset.evidenceActive = key;
    };
    linked.forEach((item) => {
      const key = item.dataset.evidence;
      item.addEventListener("mouseenter", () => {
        clearTimerList(timers);
        root.classList.remove("is-acme-sequencing", "is-evidence-playing");
        setActive(key);
      });
      item.addEventListener("focus", () => setActive(key));
      item.addEventListener("click", () => {
        clearTimerList(timers);
        root.classList.remove("is-acme-sequencing", "is-evidence-playing");
        setActive(key);
      });
    });
    const playEvidence = (instant) => {
      clearTimerList(timers);
      if (instant) {
        setActive("pricing");
        root.classList.add("is-evidence-complete");
        return;
      }
      root.classList.add("is-acme-sequencing");
      sequence.forEach((key, index) => {
        timers.push(window.setTimeout(() => setActive(key), index * 1080));
      });
      timers.push(window.setTimeout(() => {
        root.classList.remove("is-acme-sequencing");
        root.classList.add("is-evidence-complete");
      }, sequence.length * 1080 + 260));
    };
    if (replay) replay.addEventListener("click", () => playEvidence(false));
    playWhenVisible(root, playEvidence, 0.28);
  });

  document.querySelectorAll("[data-capture-simulator]").forEach((root) => {
    const canvas = root.querySelector("[data-capture-canvas]");
    const selection = root.querySelector("[data-capture-selection]");
    const note = root.querySelector("[data-capture-note]");
    const cursor = root.querySelector("[data-capture-cursor]");
    const replay = root.querySelector("[data-capture-replay]");
    const steps = Array.from(root.querySelectorAll("[data-capture-step]"));
    if (!canvas || !selection || !note) return;

    let startX = 0;
    let startY = 0;
    let dragging = false;
    let played = false;
    const timers = [];
    let dragAnimation = 0;
    const targetRect = { left: 0.43, top: 0.31, width: 0.48, height: 0.31 };

    const clearTimers = () => clearTimerList(timers);
    const clearDragAnimation = () => {
      if (dragAnimation) {
        window.cancelAnimationFrame(dragAnimation);
        dragAnimation = 0;
      }
    };

    const setStep = (step) => {
      steps.forEach((item) => item.classList.toggle("active", item.dataset.captureStep === step));
    };

    const clamp = (value, min, max) => Math.max(min, Math.min(max, value));

    const setRect = (x, y, width, height) => {
      const canvasWidth = canvas.clientWidth;
      const canvasHeight = canvas.clientHeight;
      const rect = {
        x: clamp(x, 10, Math.max(10, canvasWidth - 24)),
        y: clamp(y, 10, Math.max(10, canvasHeight - 24)),
        width: clamp(width, 20, Math.max(20, canvasWidth - x - 10)),
        height: clamp(height, 20, Math.max(20, canvasHeight - y - 10)),
      };
      selection.style.left = `${rect.x}px`;
      selection.style.top = `${rect.y}px`;
      selection.style.width = `${rect.width}px`;
      selection.style.height = `${rect.height}px`;
      positionNote(rect);
    };

    const setRatioRect = (left, top, width, height) => {
      setRect(canvas.clientWidth * left, canvas.clientHeight * top, canvas.clientWidth * width, canvas.clientHeight * height);
    };

    const setCursorPath = (rect) => {
      root.style.setProperty("--cursor-start-x", `${rect.left * 100}%`);
      root.style.setProperty("--cursor-start-y", `${rect.top * 100}%`);
      root.style.setProperty("--cursor-end-x", `${(rect.left + rect.width) * 100}%`);
      root.style.setProperty("--cursor-end-y", `${(rect.top + rect.height) * 100}%`);
    };

    const setCursorPosition = (x, y, opacity = 1) => {
      if (!cursor) return;
      cursor.style.left = `${x}px`;
      cursor.style.top = `${y}px`;
      cursor.style.opacity = String(opacity);
    };

    const animateDrag = (duration = 1120) => {
      clearDragAnimation();
      const start = {
        x: canvas.clientWidth * targetRect.left,
        y: canvas.clientHeight * targetRect.top,
      };
      const end = {
        x: canvas.clientWidth * (targetRect.left + targetRect.width),
        y: canvas.clientHeight * (targetRect.top + targetRect.height),
      };
      const ease = (t) => 1 - Math.pow(1 - t, 3);
      const startedAt = performance.now();
      const tick = (now) => {
        const linear = clamp((now - startedAt) / duration, 0, 1);
        const eased = ease(linear);
        const currentX = start.x + (end.x - start.x) * eased;
        const currentY = start.y + (end.y - start.y) * eased;
        setCursorPosition(currentX, currentY, linear < 0.08 ? linear / 0.08 : 1);
        setRect(start.x, start.y, Math.max(20, currentX - start.x), Math.max(20, currentY - start.y));
        if (linear < 1) {
          dragAnimation = window.requestAnimationFrame(tick);
        } else {
          dragAnimation = 0;
        }
      };
      dragAnimation = window.requestAnimationFrame(tick);
    };

    const positionNote = (rect) => {
      const noteWidth = Math.min(note.offsetWidth || 390, canvas.clientWidth - 24);
      const noteHeight = note.offsetHeight || 128;
      const left = clamp(rect.x, 12, Math.max(12, canvas.clientWidth - noteWidth - 12));
      let top = rect.y + rect.height + 14;
      if (top + noteHeight > canvas.clientHeight - 12) {
        top = rect.y - noteHeight - 14;
      }
      top = clamp(top, 12, Math.max(12, canvas.clientHeight - noteHeight - 12));
      note.style.left = `${left}px`;
      note.style.top = `${top}px`;
    };

    const showFinal = () => {
      root.classList.remove("is-dragging", "auto-playing");
      setCursorPath(targetRect);
      setRatioRect(targetRect.left, targetRect.top, targetRect.width, targetRect.height);
      setStep("save");
    };

    const playDemo = () => {
      clearTimers();
      clearDragAnimation();
      if (reduceMotion) {
        showFinal();
        return;
      }
      setCursorPath(targetRect);
      root.classList.add("auto-playing", "is-dragging");
      setStep("drag");
      setRatioRect(targetRect.left, targetRect.top, 0.04, 0.04);
      animateDrag();
      timers.push(window.setTimeout(() => {
        root.classList.remove("is-dragging");
        setCursorPosition(canvas.clientWidth * (targetRect.left + targetRect.width), canvas.clientHeight * (targetRect.top + targetRect.height), 0);
        setStep("note");
      }, 1720));
      timers.push(window.setTimeout(() => {
        setStep("save");
        root.classList.remove("auto-playing");
      }, 2500));
    };

    canvas.addEventListener("pointerdown", (event) => {
      event.preventDefault();
      clearTimers();
      clearDragAnimation();
      dragging = true;
      root.classList.remove("auto-playing");
      root.classList.add("is-dragging");
      setStep("drag");
      const bounds = canvas.getBoundingClientRect();
      startX = event.clientX - bounds.left;
      startY = event.clientY - bounds.top;
      setRect(startX, startY, 20, 20);
      canvas.setPointerCapture(event.pointerId);
    });

    canvas.addEventListener("pointermove", (event) => {
      if (!dragging) return;
      event.preventDefault();
      const bounds = canvas.getBoundingClientRect();
      const currentX = event.clientX - bounds.left;
      const currentY = event.clientY - bounds.top;
      const x = Math.min(startX, currentX);
      const y = Math.min(startY, currentY);
      const width = Math.abs(currentX - startX);
      const height = Math.abs(currentY - startY);
      setRect(x, y, width, height);
    });

    const finishDrag = (event) => {
      if (!dragging) return;
      event.preventDefault();
      dragging = false;
      root.classList.remove("is-dragging");
      setCursorPosition(0, 0, 0);
      setStep("note");
      timers.push(window.setTimeout(() => setStep("save"), 520));
      if (event.pointerId !== undefined && canvas.hasPointerCapture(event.pointerId)) {
        canvas.releasePointerCapture(event.pointerId);
      }
    };

    canvas.addEventListener("pointerup", finishDrag);
    canvas.addEventListener("pointercancel", finishDrag);
    canvas.addEventListener("dragstart", (event) => event.preventDefault());
    if (replay) replay.addEventListener("click", playDemo);

    setCursorPath(targetRect);
    setRatioRect(targetRect.left, targetRect.top, targetRect.width, targetRect.height);
    if ("IntersectionObserver" in window) {
      const demoObserver = new IntersectionObserver(
        (entries) => {
          entries.forEach((entry) => {
            if (entry.isIntersecting && !played) {
              played = true;
              playDemo();
              demoObserver.unobserve(root);
            }
          });
        },
        { threshold: 0.42 }
      );
      demoObserver.observe(root);
    } else {
      playDemo();
    }
  });

  document.querySelectorAll("[data-focus-demo]").forEach((root) => {
    const replay = root.querySelector("[data-focus-replay]");
    const targets = Array.from(root.querySelectorAll("[data-focus-target]"));
    const timers = [];
    const setTarget = (target) => {
      root.dataset.focusTarget = target;
      targets.forEach((item) => item.classList.toggle("active", item.dataset.focusTarget === target));
    };
    const setPhase = (phase) => {
      root.dataset.focusPhase = phase;
    };
    const playFocus = (instant) => {
      clearTimerList(timers);
      root.classList.remove("is-focus-complete");
      if (instant) {
        setPhase("complete");
        setTarget("primary");
        root.classList.add("is-focus-complete");
        return;
      }
      setPhase("flash");
      setTarget("primary");
      timers.push(window.setTimeout(() => setPhase("candidates"), 360));
      timers.push(window.setTimeout(() => {
        setPhase("primary");
        setTarget("primary");
      }, 820));
      timers.push(window.setTimeout(() => {
        setPhase("support");
        setTarget("support");
      }, 1420));
      timers.push(window.setTimeout(() => {
        setPhase("noise");
        setTarget("noise");
      }, 2020));
      timers.push(window.setTimeout(() => {
        setPhase("complete");
        setTarget("primary");
        root.classList.add("is-focus-complete");
      }, 2760));
    };
    targets.forEach((item) => {
      const target = item.dataset.focusTarget;
      item.addEventListener("click", () => {
        clearTimerList(timers);
        setPhase("complete");
        setTarget(target);
      });
    });
    if (replay) replay.addEventListener("click", () => playFocus(false));
    playWhenVisible(root, playFocus, 0.36);
  });

  document.querySelectorAll("[data-event-card-demo]").forEach((root) => {
    const replay = root.querySelector("[data-event-card-replay]");
    const timers = [];
    const playCard = (instant) => {
      clearTimerList(timers);
      root.classList.remove("is-card-complete");
      root.dataset.cardPhase = "screenshot";
      if (instant) {
        root.dataset.cardPhase = "complete";
        root.classList.add("is-card-complete");
        return;
      }
      timers.push(window.setTimeout(() => { root.dataset.cardPhase = "evidence"; }, 560));
      timers.push(window.setTimeout(() => { root.dataset.cardPhase = "entities"; }, 1180));
      timers.push(window.setTimeout(() => { root.dataset.cardPhase = "actions"; }, 1760));
      timers.push(window.setTimeout(() => {
        root.dataset.cardPhase = "complete";
        root.classList.add("is-card-complete");
      }, 2320));
    };
    if (replay) replay.addEventListener("click", () => playCard(false));
    playWhenVisible(root, playCard, 0.34);
  });

  document.querySelectorAll("[data-arch-console]").forEach((root) => {
    const replay = root.querySelector("[data-stage-replay]");
    const playStage = () => {
      root.classList.remove("is-stage-playing");
      void root.offsetWidth;
      root.classList.add("is-stage-playing");
    };
    root.addEventListener("click", (event) => {
      if (event.target.closest("[data-tab]")) {
        window.setTimeout(playStage, 0);
      }
    });
    if (replay) replay.addEventListener("click", playStage);
    playWhenVisible(root, (instant) => {
      if (!instant) playStage();
      else root.classList.add("is-stage-playing");
    }, 0.34);
  });

  document.querySelectorAll(".command-workbench").forEach((root) => {
    root.addEventListener("click", (event) => {
      if (!event.target.closest("[data-tab]")) return;
      root.classList.remove("is-command-playing");
      void root.offsetWidth;
      root.classList.add("is-command-playing");
    });
    playWhenVisible(root, (instant) => {
      if (!instant) root.classList.add("is-command-playing");
    }, 0.34);
  });

  document.querySelectorAll(".trust-lab").forEach((root) => {
    root.addEventListener("click", (event) => {
      if (!event.target.closest("[data-tab]")) return;
      root.classList.remove("is-trust-playing");
      void root.offsetWidth;
      root.classList.add("is-trust-playing");
    });
    playWhenVisible(root, (instant) => {
      if (!instant) root.classList.add("is-trust-playing");
    }, 0.34);
  });

  const revealItems = document.querySelectorAll(".reveal");
  if ("IntersectionObserver" in window && revealItems.length) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("visible");
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.14 }
    );
    revealItems.forEach((item) => observer.observe(item));
  } else {
    revealItems.forEach((item) => item.classList.add("visible"));
  }
})();
