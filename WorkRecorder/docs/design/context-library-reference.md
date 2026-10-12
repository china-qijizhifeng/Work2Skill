# WorkRecorder Context Library Reference Design

## Reference Intent

This redesign uses `/Users/example/Desktop/9ba1bafb-e85d-4352-b361-70c438e66cd1.png` as a visual and material reference, not as a content template.

WorkRecorder should feel like a local-first macOS context console: light glass surfaces, calm spacing, soft prism edges, and context objects that are easy to scan and control.

## Product Translation

| Reference Area | WorkRecorder Implementation |
| --- | --- |
| Left app sidebar | Source-list style navigation with brand, primary product modules, privacy status, and local storage anchor |
| Top search | Context library search for title, note, source, and extracted text |
| Trust capsule | `默认私有 · 本机优先 · Agent 可控` |
| Card wall | Context Capsules, each representing a saved context object |
| Card lock mark | Raw artifacts are locked unless explicitly allowed |
| Card preview | Screenshot thumbnail with Light Lens overlay |
| Detail view | Right inspector for Agent-visible info, screenshot, text, raw materials, and diagnostics |

## Information Architecture

Primary Workbench page is now `上下文库`.

The page focuses on asset browsing:

- Search contexts.
- Filter by content type and Agent readiness.
- Scan recent context cards.
- Open an inspector for the selected context.

`开始使用` owns setup and permission checklist. `截图记录` remains the chronological history view.

## Visual System

Target material mix:

- 70% frosted cyan-white glass.
- 20% optical prism edge.
- 10% satin rim.

Use prism only at edges, selected states, thumbnail lens borders, and action surfaces. Do not place prism behind reading text.

## Card Standard

Each Context Capsule card must show:

- Thumbnail with lock state.
- Title.
- Source app and time.
- User note or fallback explanation.
- Visibility mode: `安全摘要`, `工作上下文`, `完整证据`, or `待复核`.
- More menu affordance.

The card should not expose `artifact`, `bbox`, `selection_map`, or raw IDs. Those belong only in the diagnostics tab.

## Detail Standard

Single click opens the right inspector.

The inspector answers:

- What will Agent see by default?
- Which screenshot or text evidence exists?
- Which material is locked?
- What diagnostic facts explain extraction quality?

Tabs remain user-facing: `摘要`, `截图`, `文本`, `原料`, `诊断`.

## Round Acceptance Checklist

- The overview resembles a context library, not a settings page.
- Cards are aligned in a grid and do not clip text.
- Sidebar, canvas, cards, and inspector use one glass material family.
- Search and filters are visible without competing with cards.
- Empty, selected, and narrow states remain usable.
