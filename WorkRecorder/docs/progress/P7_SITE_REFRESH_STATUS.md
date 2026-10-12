# P7 Site Refresh Status

## 2026-05-30 Gap Audit

User feedback was correct: the first Astro refresh changed the visual theme but did not fully preserve the old site's strongest product storytelling. The main gaps were:

- Homepage looked like a polished feature summary, not a product story that starts from user pain.
- Screenshot/product page had a capture simulator, but lacked the old "target/source detection" explanation that makes WorkRecorder feel different from a screenshot tool.
- Recording page described keyframes and Skill drafts, but the UI did not show the handoff from recording to workflow candidate to CUA dry-run strongly enough.
- Agent page had CLI examples, but needed to include recording timeline and Skill/CUA reuse.
- Governance page needed a concrete "what did the agent read" replay example instead of abstract safety copy.
- Architecture page needed a product-level animated flow for both screenshot and recording, not just schema names.

## Changes Landed

- Reordered homepage story so pain points appear before the ACME evidence demo.
- Restored product storytelling around "evidence, not screenshots" with an ACME proof flow.
- Added `AppProviderRoutingDemo` to show system-first capture, surface detection, primary/secondary App sources, and provider routing without making Chrome the product definition.
- Strengthened Active Capture with a visible `recording_id -> keyframes -> trace -> workflow candidate -> skill draft -> CUA dry-run` handoff rail.
- Updated operation trace language to the three-level model: raw signal, target ref, semantic hint.
- Updated architecture demo labels to user-facing concepts while keeping the traceability path visible.
- Split share/error enums out of `packages/contracts/enums.py` so quality gates stay green.

## Verification

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`
- `python -m scripts.quality_gate --skip-swift`
- Playwright smoke across desktop and mobile for homepage, product, active capture, agents, governance, and architecture pages.
- Playwright interaction smoke for screenshot drag, provider route switching, and recording timeline/CUA step switching.

## Remaining Review Items

- Need one more product/UI review pass after the reviewer agents return.
- Consider adding a lighter mobile representation for provider routing if mobile page length becomes a concern.
- Consider a richer visual screenshot capture animation on homepage if the ACME proof flow still feels too dense.

## 2026-05-30 Site Fix Iteration — Reviewer Gap Closure

Reviewer feedback called out that the refreshed site still behaved like a concept deck in several places. This iteration tightened the product story and restored concrete interaction proof:

- Homepage hero now uses the short “screen现场 -> evidence -> Agent citation” proof animation instead of opening with the full Workbench mock.
- Product screenshot simulator now supports a real note field, save action, and post-save `evt_*` evidence-card state instead of only showing status steps.
- Provider routing demo now shows route decisions with overlap/capability/skipped reasons: system always runs, browser is selected as an example, collaboration/PDF are candidates/fallbacks, and every outcome goes to the event ledger.
- Governance audit demo now includes field-level mini logs: retrieval_call_id, returned_fields, snapshot_id, policy decision, citation id, and usage record.
- Architecture demo now includes the runtime boundary chain: Agent Skill -> workrecorder CLI -> local daemon -> event ledger -> disclosure -> citation.
- Screenshot drag cursor no longer disappears immediately at pointer-up; it stays aligned with the released selection corner before fading.

Verification in progress:
- `npm --prefix site run check` passed with 0 diagnostics.

Verification update:
- `npm --prefix site run check` passed with 0 diagnostics after the interaction fixes.
- `npm --prefix site run build` passed and generated 7 static pages.
- `python -m scripts.audit_static_site --site-dir site/dist` passed with 0 findings.
- `python -m scripts.quality_gate --skip-swift` passed after splitting active capture service helpers below the hard file-length threshold.
- QA screenshots saved under `.qa/site-refresh/` for home/product smoke review.

## 2026-05-31 Site Fix Iteration — Old-Site Story And Interaction Recovery

User review called out that the Astro refresh still missed the old site's strongest parts: pain-first product storytelling, screenshot overlay behavior, CLI/Agent animation, recording-to-skill/CUA mock, and concrete audit examples. This iteration restored those ideas in the new pearl-glass visual system:

- Homepage now opens with the problem and a short "screen现场 -> evidence -> Agent citation" animation, then continues into the ACME multi-source proof flow.
- Added `PainEvidenceStory` so the site explicitly contrasts today's broken screenshot/copy-prompt workflow with WorkRecorder's event/evidence package.
- Product page now treats browser as one example of an extensible App provider; PDF, IDE, chat, Feishu, CRM are described as first-class future information sources.
- Screenshot simulator copy now says the product generates an evidence card; the interaction remains a user-drawn selection with a light note/save panel.
- Active Capture page now includes `RecordingSkillShowcase`: recording a window becomes storyboard keyframes, human action trace, Workflow Candidate, Skill Draft, and CUA dry-run.
- Agent examples now use the ACME scenario end to end instead of an unrelated site-redesign example.
- Governance page now shows the full accountability chain: before capture, storage, retrieval, and after usage, plus concrete retrieval/snapshot/citation records.
- Architecture page now shows input/process/output for screenshot and recording flows, keeping the product explanation readable without dumping protocol fields.
- Browser-visible animation loops now start only when their section is near the viewport, reducing offscreen motion and making the first visible frame more coherent.
- Fixed `product.html#capture` anchor behavior by removing global smooth-scroll on initial hash loads; verified in browser that the capture section lands below the sticky header.
- Fixed 390px mobile overflow in the screenshot simulator; the capture canvas now fits the viewport instead of forcing a 560px min-content width.

Reviewer closure:
- Product/story review: ACME scenario continuity restored; recording is now framed as "screenshot solves a moment, recording solves a process."
- UI/interaction review: offscreen animation timing fixed, capture drag clamping fixed, mobile overflow fixed, and active-capture initial state now matches the visible first step.
- Remaining P2: hero typography is still intentionally bold; if it feels too poster-like after user review, lower the H1 size and give the proof animation more vertical weight.

Verification:
- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`
- `python -m scripts.quality_gate --skip-swift`
- Playwright desktop smoke for `/`, `/product.html#capture`, `/active-capture.html`, `/agents.html`, `/governance.html`, `/architecture.html`.
- Playwright mobile smoke at `390x844`; no horizontal overflow after the capture simulator fix.

## 2026-05-31 Site Review Iteration — Product Language And Disclosure Consistency

Two reviewer passes found that the site was visually stronger but still carried several credibility risks: public copy mixed current capabilities with future recording automation, some sections still used internal object names, and the share copy seemed to contradict the governance page around screenshots.

Changes landed:

- Reframed public copy from “Agent / event / provider / raw” toward user-facing terms: Agent、本机记录、来源补齐、安全摘要、原件、引用记录.
- Homepage proof animation now has a visible Agent answer/citation card, so the third step is no longer only a highlighted text tile.
- Screenshot simulator default selection now targets the pricing risk/KPI area more deliberately; the note sheet is hidden until the note step so it feels less like a toy overlay.
- Active Capture and Recording-to-Skill demos now use “流程草稿 / 用户确认 / 安全试跑” language, with staged highlight states instead of static same-weight panels.
- Share and governance copy now use one consistent model: search/Agent defaults to safe summary; when a user explicitly clicks share, the screenshot is included as a controlled attachment, while source code/UI tree/local paths remain locked.
- `scenarios.html` no longer reads like a construction notice; it is a noindex transitional entry to product and recording pages.
- Mobile H1 sizing and line-height were reduced after visual review; verified at 390px with no horizontal overflow.

Verification:

- `npm --prefix site run build`
- `npm --prefix site run check`
- `python -m scripts.audit_static_site --site-dir site/dist`
- Playwright smoke at desktop `1440x900` across home/product/recording/agents/governance/architecture.
- Playwright mobile smoke at `390x844`; H1 fits within viewport and `scrollWidth == clientWidth`.

Remaining P2:

- Active Capture is still dense by nature; next pass could replace the full three-column desktop demo with a single-window guided sequence.
- Agent page still includes CLI examples because the product is local/agent-facing; for a pure marketing audience, those should become a collapsed developer detail.

## 2026-05-31 Site Refocus Iteration — Reduce Noise And Rebuild Recording Story

User review correctly called out that the site still felt cluttered: too many equal-weight cards, too much concept language, and the recording page did not yet show the simple product promise of "human demo -> agent learns a workflow draft -> CUA can safely try it." This pass focused on narrative direction rather than adding another feature section.

Round 1 changes:

- Homepage H1 briefly changed from a broad concept line to a too-casual product action; this was later rejected and replaced.
- Homepage hero added a three-line pain/action/result strip so first-screen visitors see the product problem before reading detailed sections.
- Active Capture page now uses a single main recording showcase in the hero; the previous duplicate animation below the fold was removed.
- Recording page copy now says "流程草稿" and "确认后才试跑" instead of implying the Agent immediately learns or controls the computer.

Round 1 reviewer notes:

- Product reviewer: direction is clearer, but recording still looked like four peer cards instead of a before/after demonstration.
- UI reviewer: hero typography is less harsh, but the recording demo needed a stronger left-right "human operation vs CUA dry-run" contrast.
- Risk reviewer: "学会" copy can overpromise; keep "草稿 / 确认 / dry-run" language in prominent positions.

Round 2 changes:

- Recording showcase now labels the flow as 人类演示 -> 关键帧整理 -> 流程草稿 -> CUA 试跑.
- Left and right stages were visually weighted up: human recording and CUA dry-run now act as the main before/after anchors.
- Added a compact bridge inside the storyboard stage: video -> keyframes -> steps.
- Added a Skill preview inside the candidate stage to make "沉淀成 Skill" explicit without claiming it is already published.
- CUA stage now displays `dry-run · 等待确认` inside the mock UI and the final action log stops at confirmation.

Round 2 reviewer notes:

- Product reviewer: recording story is now understandable without reading the page body.
- UI reviewer: still dense, but the page has one central demonstration instead of two competing ones.
- Engineering reviewer: implementation stayed within the existing Astro component/CSS structure; no new framework or runtime dependency added.

Round 3 changes:

- Homepage removed the share/import section from the primary story so the main line is now only: screenshot, recording, Agent use.
- `coreCapabilities` changed from "save/appshot/share" to the clearer product triad: 截图 / 记录 / Agent.
- Share remains available on the product page, but no longer competes with the homepage story.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`

Follow-up copy alignment:

- User asked to use `Agent` instead of `Agent` in the public site.
- All user-facing site source under `site/src` now uses `Agent`; a spacing audit confirms there are no squeezed forms such as `Agent使用` or `给Agent`.
- Re-ran `npm --prefix site run check`, `npm --prefix site run build`, and `python -m scripts.audit_static_site --site-dir site/dist`.

## 2026-05-31 Reviewer Iteration 5 — Mobile And Storyline Follow-Up

Second-round reviewers found no P0 issues, but identified several P1/P2 polish gaps around mobile readability and story clarity.

Changes landed:

- Homepage first screen was simplified again: the four pain bullets moved below the fold into the pain section, and the hero trust strip was reduced to three items.
- Product page third stage now owns a new job: “Agent可见性账单”. It no longer repeats provider/source completion copy.
- Recording storyboard keeps all four cards visible and only highlights the active one, so the process reads as a full story rather than a single changing card.
- Recording state 2 now emphasizes the WorkRecorder lens instead of keeping the human window visually primary.
- Mobile ACME chat source no longer lets the selection overlay and chip cover the chat content.
- Agent Skill demo no longer creates an inner scroll container on mobile.
- Evidence buttons now sync `aria-pressed`; Agent Skill flow nodes are keyboard-focusable.

Reviewer closure:

- Product reviewer: P1 around hidden storyboard cards and product-page repetition is closed.
- UI reviewer: P1 mobile obstruction and inner scrolling risk is closed.
- Accessibility follow-up: evidence and agent-stage controls now expose clearer interaction state.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`
- Browser snapshot smoke with the local Astro dev server on home, product desktop, product mobile, Active Capture, Agents, and Governance.
- Product mobile `scrollWidth == clientWidth == 390`, so no horizontal overflow after the mobile ACME fix.

Remaining P2:

- Active Capture still uses a dense four-stage desktop layout; a later pass could convert it into a true cinematic single-scene animation.
- Some lower sections still rely on glass cards for explanation; the homepage is cleaner, but product/architecture pages can be further differentiated with more bespoke scenes.

## 2026-05-31 Site Refocus Iteration 2 — Pain-First Copy And Cinematic Recording

User review rejected two issues in the previous pass:

- The casual screenshot wording sounded artificial for a serious product homepage.
- The old site's "why this exists" pain points had been over-pruned, leaving the product motivation too thin.

Changes landed:

- Homepage H1 now says: "把刚发生的工作现场，整理成Agent能引用的证据。"
- Hero supporting copy now explicitly mentions the old manual workflow: screenshot, web page, chat record, background explanation, and prompt assembly.
- First-screen pain strip expanded to four concrete problems: 信息散、截图弱、搬运累、结果虚.
- Pain section copy now restores the old-site thesis: screenshots only preserve pixels, recordings only support playback, copy-prompt workflows lose source/time, and answers become hard to replay.
- Recording page hero title changed from "让Agent学会" to "整理成可审查的流程草稿" to avoid overpromising automation.
- `RecordingSkillShowcase` was rebuilt into a more cinematic single scene:
  - left side: human demonstration window;
  - center: WorkRecorder lens with step controls;
  - right side: CUA dry-run window;
  - bottom: four key storyboard cards.
- Added `data-recording-cinema` interaction logic so the step controls and storyboard state advance together.
- Removed the final duplicate four-card explanation block from Active Capture, reducing visual clutter.

Reviewer notes:

- Product reviewer: homepage motivation is stronger and closer to the old site; the casual screenshot wording issue is closed.
- UX reviewer: recording page now has a clearer left-to-right before/after mental model; still future work to make it more animated/illustrative, but it no longer reads as a pile of cards.
- Risk reviewer: "learns workflow" language has been softened to "流程草稿 / 确认 / dry-run".

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`
- Browser snapshot smoke for home and Active Capture through the local dev server.

## 2026-05-31 Site Refocus Iteration 3 — Remove Trial Copy And De-Engineer Agent Demo

User review asked to directly remove the local trial/install language from the public site and keep the product story focused. This pass removed the install/beta CTA layer and softened the visible command demo.

Changes landed:

- Removed homepage and header local-trial CTAs.
- Removed the product-page local download/install section and its anchor.
- Verified no source-visible residue for the previous trial/install wording.
- Replaced exposed English command tabs in the Agent workflow demo (`search`, `inspect`, `bundle`, `usage`, `recording`) with Chinese task labels: 粗搜、精查、打包、留痕、片段.
- Translated terminal sublabels such as `safe cards`, `selected record`, and `recording timeline` into user-facing Chinese labels.

Reviewer notes:

- Product reviewer: removing install language keeps the site from sounding like a dev distribution page.
- UX reviewer: command examples are still available for the agent-facing page, but the first visible layer now reads as a workflow rather than raw CLI taxonomy.
- Risk reviewer: no feature promise was added; the removed copy only narrowed the public story.

Verification:

- Source grep found no remaining trial/install CTA strings.
- Source grep found no remaining visible English tab labels from the command demo.

## 2026-05-31 Reviewer Iteration 4 — Reduce Demo Density And Fix Interaction Truth

Four reviewer passes were run in parallel: product narrative, UI/UX, interaction animation, and code structure. They agreed on the same root issue: the site had become a glass-card demo gallery, and several animations looked like static mocks instead of proof of product behavior.

Changes landed:

- Homepage ACME demo was cut from four visible sources to two: pricing page + collaboration thread. This keeps the proof focused on “saved screen现场 -> evidence -> answer citations” instead of a sales-dashboard collage.
- ACME metrics now show 2 来源 / 2 记录 / 2 引用; CRM/mail proof noise was removed from the homepage demo.
- Agent demo no longer exposes a command block as the primary visual. It now shows a four-step Agent action bill, with CLI examples collapsed under details.
- Governance replay no longer leads with log-style keys such as `retrieval_call_id` and `snapshot_id`; it now shows a human-readable receipt, with IDs demoted to small audit references.
- Governance replay now auto-advances through 粗搜 -> 深入 -> 引用 -> 锁定 when visible, so “可复盘” reads as a sequence rather than a static card.
- Recording cinema now gates cursor motion by state: human cursor moves only during “录制窗口”, and CUA cursor moves only during “安全试跑”. This closes the previous bug where CUA appeared to act before confirmation.
- Recording copy changed from “学习怎么做” to “整理做法草稿” to avoid overpromising automation.
- Screenshot simulator starts without showing the final selection rectangle; the selection appears only during replay or real pointer drag.
- `ProductWorkbench` interactions now initialize all `[data-hero-demo]` instances, not just the first one.
- Removed the unused old recording demo component, its dead script block, and stale CSS.
- Product page was reduced from repeated screenshot/appshot/share sections to three focused stages: 捕捉 -> 来源补齐 -> 给Agent读取. Share/import no longer competes with the screenshot page story.

Reviewer closure:

- Product reviewer: homepage proof is now narrower and less noisy, though future work should turn the hero into one even stronger single-scene story.
- UI reviewer: the CUA/human motion gating fixed a credibility issue; remaining future work is to reduce glass-card surfaces further.
- Interaction reviewer: P1 bugs around unused recording code and always-running cursors are closed; CLI and audit demos now have clearer behavior.
- Code reviewer: dead recording demo code was removed and multiple workbench instances now initialize correctly.
- Product reviewer follow-up: screenshot page now answers one job instead of trying to also explain sharing, appshot, and install/distribution.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`

## 2026-05-31 Reviewer Iteration 6 — Product Definition And Causal Motion

User asked for actual reviewer critique instead of self-review. Two desktop-only reviewer agents reviewed product narrative and UI/animation quality.

Reviewer findings:

- Product reviewer: homepage still felt like a context/evidence concept before it felt like a concrete macOS product; pain points were abstract, and screenshot/recording/agent appeared visually equal even though screenshot + agent is the current core loop.
- UI reviewer: no P0, but product and agent pages still had too many equal-weight glass containers; recording-to-skill needed a stronger causal handoff from human demo to WorkRecorder整理 to CUA dry-run.

Changes landed:

- Homepage H1 and lead now define WorkRecorder as a macOS local context hub instead of only saying “整理成证据”.
- Hero CTA now points to the screenshot-to-evidence-card product behavior first, and Agent citation second.
- Pain section changed from abstract labels to a concrete meeting-prep failure chain: 找报价、翻讨论、补链接、写背景、追出处.
- Core capability labels now clarify maturity: `Now · 截图`, `Core · Agent`, `Next · 记录`.
- Homepage ACME demo hides internal `cit_*` / `evt_*` identifiers from the primary story and uses human-readable references instead.
- Recording cinema now includes visible flowing evidence tokens moving from human demo through the WorkRecorder lens to CUA dry-run.
- Agent page replaced the four equal step cards with a single pipeline: 用户问题 -> 本机检索 -> 精查证据 -> 带引用回答.
- Agent demo no longer uses an internal scroll container on desktop; the visible flow is simpler and more causal.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- Browser snapshot smoke for homepage, Active Capture, and Agents through the local dev server.

## 2026-05-31 Reviewer Iteration 7 — Product First, CLI Second

Two more desktop reviewers reviewed the updated site.

Reviewer findings:

- Product reviewer: no P0, but homepage still used concept-first language; screenshot/agent/recording maturity was still blurred by navigation order and page weight; product page did not put screenshot capture first; agent page still felt like CLI documentation.
- UI reviewer: no P0, but the site still reused too many glass-card shells; Active Capture needs more visible object transformation; Agent/Governance/Architecture need stronger page-specific visual systems over time.

Changes landed:

- Navigation order changed to `首页 -> 截图体验 -> Agent使用 -> 记录片段 -> 安全 -> 原理`, so current core loop precedes next-stage recording.
- Homepage copy now starts with a concrete action: press the shortcut, frame a work moment, add a note, get a local evidence card the Agent can cite.
- Homepage proof cards changed from abstract labels to user-facing steps: 保存现场、自动补齐、回答引用.
- Product page now places the screenshot simulator directly in the hero. The Workbench mock moved to the “保存之后” section.
- Agent page removed the command workbench from the primary narrative. The main visible story is now: user question -> safe summaries -> two selected evidence records -> cited answer. CLI examples remain collapsed as implementation detail.
- Governance audit copy no longer surfaces internal event/citation IDs in primary receipt rows.
- Architecture page copy changed from product-pipeline jargon to a user-facing protection path: 保存、整理、过滤、引用、复盘.
- Old `scenarios.html` transition page no longer highlights the recording nav item and points first to the current product flow.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`
- Browser desktop smoke for `/`, `/product.html`, and `/agents.html` through the local dev server.

Remaining P1/P2 candidates:

- Active Capture should eventually show actual keyframe thumbnails being produced and merged into a flow draft, not only animated evidence chips.
- Governance and Architecture still share too much visual language with the rest of the site; future pass should make them ledger/table and topology oriented instead of glass-card oriented.

## 2026-05-31 Reviewer Iteration 8 — Visible Handoff And Plain Governance

One more strict product/UI reviewer pass focused on the latest desktop site.

Reviewer findings:

- No P0.
- P1: Recording -> Skill/CUA still looked decorative. The CUA window was present from the beginning, so the flow still felt like three panels side by side instead of human demo -> keyframes -> draft -> confirmed dry-run.
- P1: Governance used friendlier labels than before, but still mixed user questions with internal terms such as `复盘编号`, `交付快照`, and `原件字节`.
- P1: Architecture had a count mismatch: hero said five things, CTA and timeline said six stages.
- P2: Active Capture repeated the same “not ordinary recording” promise across too many card surfaces.

Changes landed:

- Recording cinema now shows an explicit lock note over the CUA window until the `安全试跑` state. The agent-side UI is blurred/dimmed before user confirmation, making the safety boundary visible.
- WorkRecorder lens now changes label by state: `等待演示`, `抽关键帧`, `生成草稿`, `交给试跑`.
- The “not ordinary recording” section changed from four equal glass cards into one compact ledger-style rule list, reducing the card-stack feeling.
- Governance disclosure rows are now phrased as three user questions: what the Agent sees by default, what it sees after opening a record, and what always requires approval.
- Governance audit receipts removed primary UI terms like `复盘编号`, `交付快照`, and `原件字节`, replacing them with human-readable statements.
- Architecture copy now consistently uses six steps, and the lower cards explain multi-source capture and “find first, expand later” without leading with indexing jargon.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`

Remaining P1/P2 candidates:

- The recording handoff is now safer and clearer, but a future pass can make the keyframe thumbnails physically travel into the draft card with stronger motion.
- Governance and Architecture are readable, but could still be more visually distinctive with one dedicated ledger/topology illustration each.

## 2026-05-31 Reviewer Iteration 9 — Remove Remaining Inner-Circle Terms

Reviewer rechecked the latest state.

Reviewer findings:

- No P0/P1.
- P2: Recording handoff is clearer, but the keyframe/draft objects can still become more central in a future animation pass.
- P2: Governance still had a few product-insider words such as `粗搜`, `交付字段`, and `记录编号`.
- P2: Architecture was consistent on six steps, but the inspector still showed engineering chain labels such as `本机命令` and `本机服务`.

Changes landed:

- Governance tabs now read as user actions: `找记录`, `打开证据`, `引用`, `锁定`.
- Governance receipts now say `给Agent看的内容` instead of `交付字段`, and explain selected records instead of `记录编号`.
- Architecture flow inspector now says `Agent提出问题 -> 本机检查权限 -> 只交付允许内容 -> 回答带引用 -> 使用记录可查`.
- Recording lens artifacts are now exposed as a named visual object (`关键帧合成流程草稿`) instead of hidden decoration.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`

## 2026-05-31 Reviewer Iteration 10 — Product Copy And Demo Cleanup

Reviewer rechecked the desktop product story after the prior visual pass.

Reviewer findings:

- No P0.
- P1: Product screenshot page still had an engineering routing demo with overlap/confidence language. It made the page feel like an infra console instead of a product walkthrough.
- P1: Active Capture repeated the same “not ordinary recording” promise across too many surfaces, making the page feel card-heavy and unfocused.
- P1: Agent page still read like an API guide in places, with terms such as “粗搜卡 / 精查证据 / 记录编号”.
- P2: Several deleted/old demos left unused source and CSS (`CommandWorkbench`, provider routing styles/scripts), which risked drifting back into the page.

Changes landed:

- Product page now replaces the provider-routing demo with a simple three-part summary: window identity, recognized text, and graceful save even when enrichment is missing.
- Product Workbench no longer foregrounds sharing as a core homepage story; the example card is a concrete competitor-pricing capture.
- Active Capture keeps the cinematic recording demo as the main proof and collapses the lower content into a compact outcome panel: video playback, keyframes, safe text, and confirmed workflow draft.
- Agent copy now uses natural user actions: summary card, open a specific record, answer with citations, review what was used.
- Removed stale CommandWorkbench and AppProviderRoutingDemo source, routing script handlers, and old CSS blocks.
- Replaced visible “OCR” labels in product-facing cards with “识别文字” except where code/CSS names are internal.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`

Remaining P1/P2 candidates:

- A fresh reviewer pass is running against the cleaned source to catch remaining copy or dead-code issues.
- Browser visual validation is still limited by local Browser tool access in this environment; source/build/static audit are clean, but a later visual pass should compare desktop screenshots again.

## 2026-05-31 Reviewer Iteration 11 — Dead Demo Removal And Public Copy Polish

Reviewer Avicenna rechecked the cleaned source after Iteration 10.

Reviewer findings:

- No P0/P1.
- P2: Agent page still exposed a raw command block, which made the product story slip back into implementation details.
- P2: `ShareFlow` had been deleted as a component, but its script and CSS remained.
- P2: Product page still used words like `协议`, `路由或插件`, `索引`, `模型`, and `可见性账单` in visible copy.
- P3: The stale `scenarios.html` route still built a noindex transition page and mentioned old share/import positioning.

Changes landed:

- Agent page now shows a plain four-step usage summary instead of raw `workrecorder ... --json` commands.
- Removed stale ShareFlow runtime handlers and CSS.
- Deleted the stale `scenarios.astro` route; the site now builds six current pages only.
- Product copy now says “接入细节 / 可读文字 / 能看什么” instead of protocol/routing/index/model language.
- Governance copy now says “只给允许看的内容 / 留下可查记录 / 实际返回内容” instead of permission-filtering and audit-bill language.
- Public source scan now only finds internal CSS/class names such as `drawer-title`, not visible engineering copy.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`

Remaining notes:

- Full repository quality gate currently fails on Python import sorting in the broader active-capture worktree, outside the site refresh files. Site-specific check/build/audit are clean.

Quality follow-up after Iteration 11:

- Split `packages.indexing.search` out of the oversized indexing service so the repository quality audit no longer flags `packages/indexing/service.py` as too long.
- Replaced the lingering indexed `user_note` literal with the typed `IndexFieldKind.USER_NOTE.value` path.
- Normalized Python imports across the active-capture/indexing changes that were already present in the worktree.

Verification:

- `python -m scripts.quality_gate --skip-swift` passed: 354 Python tests passed, 5 skipped; site build/check/audit passed; browser extension typecheck/build/tests passed.

Desktop visual smoke after Iteration 11:

- Captured live desktop screenshots for `/`, `/product.html`, `/active-capture.html`, `/agents.html`, `/governance.html`, and `/architecture.html` at 1440x1100 into `.qa/site-review/`.
- Generated `.qa/site-review/contact-sheet.png` for side-by-side review.
- Current visual read: homepage now exposes the pain section below the hero, product page is cleaner and no longer dominated by route/debug language, active-capture page centers the human-demo-to-Agent-trial animation, and governance/architecture are calmer than the previous card-heavy version.
- Note: Chrome headless on this machine times out after writing screenshots, so screenshots were treated as generated artifacts and the local dev server logs confirmed HTTP 200 responses for all six pages.

## 2026-05-31 Reviewer Iteration 12 — CTA, Real Agent Flow, And Cross-App Claims

Reviewer Rawls and Franklin rechecked the refreshed site after the cleanup pass.

Reviewer findings:

- P1: The public site explained the product but did not give visitors a concrete next action after understanding it.
- P1: The Agent workflow proof was too generic; after adding a console, reviewer noted it still needed to match the actual CLI shape.
- P1: The cross-App source story was inconsistent: some copy implied PDF/chat/business-system providers already enrich content, while the product page correctly said they are future/extensible sources.
- P2: Active Capture primary CTA jumped to an outcome summary instead of the demo/result section.
- P2: A few abstract terms remained in visible copy, including `上下文层`, `保护路径`, and broad source claims.

Changes landed:

- Added a persistent `安装试用` CTA to the desktop nav and mobile nav.
- Changed the homepage secondary CTA to the real installation guide instead of another internal explanation anchor.
- Added `AgentTraceConsole`, a compact concrete workflow that shows `agent begin`, `events search`, `events inspect`, and `usage record`, with the actual safe fields and run-ledger loop.
- Added a cross-App source matrix on the screenshot/product page: all screenshots get system evidence; browser is the current enrichment example; PDF/doc/chat/business apps are explicitly future/extensible sources.
- Reworded homepage and architecture source claims so only browser enrichment is presented as the current example; other apps are described as future sources that can connect through the same model.
- Replaced visible `WorkRecorder 上下文层` with `WorkRecorder 保存的记录`, and `保护路径` with a more user-facing “一条记录怎么流转”.
- Fixed the Active Capture CTA label to `看整理结果` and its target to the result section.
- Replaced all current public/workbench occurrences of the old helper label with `Agent`.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`
- `python -m pytest tests/integration/test_active_capture_backend.py::test_active_session_view_filters_deleted_secondary_keyframe_and_timeline_entry -q`
- `python -m scripts.quality_gate --skip-swift` passed: 357 Python tests passed, 5 skipped; site build/check/audit passed; browser extension typecheck/build/test passed.

Implementation note:

- While running the full gate, a broader active-capture validation bug surfaced: action targets that referenced both a keyframe evidence id and artifact id were rejected unless both appeared on the exact same link edge. The graph now accepts the target when both refs belong to the same referenced keyframe, which matches the ledger model and restored the integration test.

Desktop visual smoke:

- Regenerated `.qa/site-review/contact-sheet.png` after the site changes. The site is calmer and now has a visible install action, an Agent workflow proof, and a clearer source model. Remaining aesthetic risk is that the entire site still shares a very mint/glass-heavy language; future polish should add more page-specific texture without reintroducing clutter.

## 2026-05-31 Reviewer Iteration 13 — Storyline Compression And Concrete Language

Reviewer Epicurus rechecked the refreshed site against the user's latest feedback.

Reviewer findings:

- P1: The homepage still stacked too many proof modules, so it felt like a collection of demos rather than one product story.
- P1: The site still leaned on repeated abstract phrases such as `安全摘要`, `流程草稿`, `故事线`, and `原始材料`, which made the copy sound generic.
- P2: Active Capture had the strongest idea, but its first fold had a large empty right side before the cinematic demo started.
- P2: Several mock panels shared the same mint/glass treatment, so priority was still hard to read.

Changes landed:

- Removed the separate homepage capability-card section. The homepage now moves from hero → pain → one concrete ACME evidence story → recording preview.
- Replaced visible abstract product phrases with more concrete wording: `默认可见`, `步骤草稿`, `关键时刻列表`, and `完整材料`.
- Reworded Agent and governance pages so the user sees "what Agent first receives" and "what needs confirmation" instead of internal disclosure jargon.
- Added a compact Active Capture hero proof card on the right side of the first fold: video for humans, keyframes/text for Agent, step draft only after confirmation.
- Kept the recording cinematic as the main proof instead of adding more cards.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- Live desktop screenshot for `/active-capture.html` regenerated at `.qa/site-review/recording-latest.png`.

Remaining notes:

- The site is less card-heavy after this pass, but it can still use one future visual polish round to add more contrast between product pages without returning to the old dark style.

## 2026-05-31 Reviewer Iteration 14 — Capture Result Closure And Recording Skill/CUA Proof

Reviewers Godel and Carson focused on the remaining product-story gaps after Iteration 13.

Reviewer findings:

- P0/P1: Recording-to-skill remained too weak. The middle step looked like an abstract lens/button column instead of a real skill or workflow draft.
- P1: The screenshot product page showed a believable drag overlay, but the first fold did not make the generated evidence card visible enough.
- P1: The recording demo needed a more explicit CUA dry-run state: find a similar control, run the steps, and stop before a risky action.
- P2: Homepage and hero copy still underweighted the future recording/skill/CUA story.

Changes landed:

- Homepage hero now says “刚看过的现场、刚演示的步骤” and points to both screenshot evidence and recording-to-steps.
- Screenshot simulator now shows inline boundary labels beside the selection: `选区进入证据` and `完整原图需确认`.
- Screenshot simulator now reveals an in-canvas result card after save: `证据卡已生成`, with note/app/time/OCR/screenshot-ref language.
- Recording demo middle column was redesigned into a visible `步骤草稿` card with keyframes, four generated steps, visual anchor, and safety stop.
- Agent/CUA replay window now includes a visible run trace: read steps, locate Enterprise, extract fields, stop before confirmation.
- Active Capture CTA now jumps directly to the recording demo and says `看 Agent 如何试跑`.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- Live desktop screenshot for `/product.html` regenerated at `.qa/site-review/product-latest.png`; it now shows the selection labels and generated evidence card in the first fold.

Remaining notes:

- Chrome headless was unstable while regenerating the recording screenshot on this machine, but the site build/check path is clean. A later browser pass should regenerate `.qa/site-review/recording-latest.png` once Chrome is stable.

## 2026-05-31 Reviewer Iteration 15 — Contract Clarity And Stage-Reveal Recording Demo

Reviewers Hume and Planck rechecked the site after Iteration 14.

Reviewer findings:

- P0: The homepage mixed today's screenshot evidence workflow with next-stage recording/CUA in the same core promise, which made the product feel less trustworthy.
- P0: The disclosure contract was inconsistent: product/search pages said search returns short cards, while governance still implied cleaned web summary was default-visible.
- P0: The recording demo showed keyframes, draft steps, and safety stops from the beginning, so it looked like three cards being highlighted rather than a causal flow from human demonstration to Agent trial-run.
- P1: Product screenshot copy said the user only did two things while the simulator correctly showed three: drag, note, save.
- P1: Capture simulator first fold hid the step rail, making the drag affordance feel more like a canned animation than a product micro-task.

Changes landed:

- Homepage now centers the current shipped story: screenshot, window, text, source, note become Agent-readable local context. Recording is still visible, but explicitly positioned as the next-stage path.
- Unified disclosure language across product, Agent and governance: `搜索短卡` → `点开记录` → `单独确认`.
- Governance hero/card now says search returns event_id, time, app, title, note, OCR text and hidden-material list; cleaned page text moved to inspect/deep-read language.
- Product hero now says the screenshot action has three steps: select, note, save.
- Product hero keeps the simulator's step rail visible so the user can understand what the drag demo is proving.
- Recording demo now reveals content by stage: early states blur/hide final draft fields; keyframes appear first, draft steps appear next, and a `确认安全试跑` gate unlocks the Agent trial-run view.
- Agent trial-run copy now shows a clearer dry-run trace: read draft, locate similar Enterprise control, simulate click/wait, extract fields, stop before submit/purchase.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`
- Live homepage screenshot regenerated at `.qa/site-review/home-after.png` using `http://localhost:4323/index.html`.

Remaining notes:

- Scope is intentionally limited to `site/`; broader active-capture Python/backend quality work is being handled separately.
- Chrome headless remains flaky for some long screenshots in this environment, but the generated homepage screenshot and all site-specific checks are clean.

## 2026-05-31 Reviewer Iteration 16 — Disclosure Consistency And Demo Believability

Reviewers Hume and Planck rechecked the site after Iteration 15.

Reviewer findings:

- P0: Full screenshot visibility was still inconsistent. Governance said full screenshot requires separate confirmation, while product/workbench copy implied it could be opened after selecting a record.
- P1: Product/search pages still left a small boundary confusion between search-card text and readable web/page text.
- P1: The homepage pain story and Agent page still leaked next-stage recording concepts into the current shipped workflow.
- P1: The screenshot simulator saved a fixed ACME result regardless of the user note or selected area, so it still felt partly canned.
- P1: The recording demo's top step 4 could be clicked directly, bypassing the semantic "confirm dry run" gate.

Changes landed:

- Unified screenshot disclosure language: search can show screenshot refs/hidden-material status; selecting a record can show a screenshot reference; full original image remains a separate confirmation.
- Product source summary now says search cards include note/title/OCR; browser/page text is only read after opening a record.
- Removed recording/keyframe references from the homepage pain story, Agent default demo, and governance current-case receipt.
- Capture simulator now derives the saved result copy from the current note text and selected area, so custom dragging/typing produces a different evidence-card message instead of a fixed ACME label.
- Recording demo top stage 4 is now locked until the user clicks the `确认安全试跑` button in the generated draft card; the UI now presents confirmation as the gate rather than just another stage tab.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`
- Public copy scan found no stale old helper labels, casual capture wording, or deprecated recording/storyline terms in current source.
- Live Active Capture screenshot regenerated at `.qa/site-review/active-capture-after.png`; it now shows the top stage controls and locked confirmation step.

Remaining notes:

- No site-specific P0 remains from the latest reviewer pass. Remaining P1/P2 polish is mostly about reducing card density further and making architecture more component-diagram-like in a future pass.

## 2026-05-31 Reviewer Iteration 13 — Desktop Site Tightening

User clarified the scope: only the public site should be changed in this pass. Backend, App, CLI, and recording implementation work are owned elsewhere.

Reviewer findings:

- Product reviewer: no P0. The site was cleaner than the previous version, but the recording-to-Skill/CUA value was still too hidden on the homepage. Governance needed a more receipt-like audit chain with approval/denial facts, and Architecture still looked too much like a linear step card rather than a system boundary diagram.
- Interaction reviewer: no P0. Desktop flow worked, but the recording demo was still tall and Architecture lacked animated stage emphasis. Mobile issues were noted but intentionally deferred because this pass is desktop-first.

Changes landed:

- Homepage proof demo now includes a fourth branch: `记录片段 -> 步骤草稿 -> CUA 试跑`, so the next-stage value appears in the first product story instead of only on the recording page.
- Product page source explanation was converted from repeated glass cards to a compact source ledger: all screenshots, browser example, PDF/doc fallback, and future chat/business-system sources.
- Governance audit demo now behaves more like an audit receipt: it includes policy decisions, grant scope, approved_by / grant_id / expires_at / revoked_at, and raw-material access state. Auto-advance was removed so users can read the receipt without it changing under them.
- Architecture hero now shows a mini system boundary map with Capture App, Local Ledger, Policy, Agent Skill, Raw Store, Safe Text Index, and Audit Log.
- Architecture flow nodes now distinguish Local Ledger + Raw Store, Policy + Safe Index, and Agent Boundary.
- Agent CLI demo now shows compact JSON outputs for begin/search/inspect/usage, making the skill workflow concrete without turning the page into raw docs.
- Visual weight was softened in several label/node styles, reducing the heavy black-text feel in mocks and architecture nodes.
- Hero vertical padding was reduced so the next section appears sooner and pages feel less like oversized concept posters.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`
- Stale public-copy scan for old terms returned clean.
- Desktop screenshots regenerated under `.qa/site-review/`: `home-final2.png`, `active-capture-final2.png`, `architecture-final2.png`, and `governance-final2.png`.

Remaining P2:

- Recording page is clearer and safer, but still high-density. A future pass can make the keyframe objects physically travel into the draft card with stronger motion.
- Architecture and Governance now have more distinct visual systems, but a future pass can add active stage highlighting to the system map rather than relying on static topology.

## 2026-05-31 Reviewer Iteration 17 — Audit-First And Recording Flow Clarification

Scope stayed limited to `site/`.

Reviewer findings:

- No P0.
- P1: recording page still required users to infer the full path from three large mock panels; the CUA dry-run step needed to be visible immediately.
- P1: governance hero showed a summary but not a real audit trail.
- P1: architecture page still had too many stacked card groups, making the system boundary feel busy.
- P2: copy had a few abstract phrases and inconsistent dry-run wording.

Changes landed:

- Recording page now includes a visible four-step flowline: `人演示 -> 抽 3 张关键帧 -> 生成 Workflow Draft -> CUA dry-run 预演`.
- Active Capture hero proof card now includes step 04: `CUA dry-run，提交前停住`.
- Recording demo wording was unified around `CUA dry-run`; the confirmation button now says `确认后开始 dry-run`.
- Governance hero now shows bill-style rows for `search_call`, `inspect_call`, `delivered_fields`, and `raw_access` before the user scrolls.
- Architecture flow removed the repeated three large boundary cards and replaced them with compact boundary tags plus a raw/safe/audit swimlane.
- Reworded a few abstract phrases: `同一套账本` -> `同一本本机使用记录`, `高价值时刻` -> concrete key moments, and `用户能理解的边界` -> concrete Agent visibility boundaries.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `./.venv/bin/python -m scripts.audit_static_site --site-dir site/dist`
- Stale-copy scan for old terms returned clean.
- Desktop screenshots regenerated under `.qa/site-review/`: `active-capture-r16.png`, `governance-r16.png`, and `architecture-r16.png`.

Remaining P2:

- The site is much clearer, but card density is still higher than ideal on Architecture. A future design pass could replace the remaining node cards with a more custom diagram if the user wants an even more editorial/product feel.

## 2026-05-31 Reviewer Iteration 19 — User-Language Receipts And Material Journey

Scope stayed limited to `site/`.

Reviewer findings:

- No P0.
- P1: recording page still used too many engineering terms (`Workflow Draft`, `CUA dry-run`, `KF`) in the main product story.
- P1: recording demo gave equal visual weight to human demo, draft, and Agent run; the user should first understand the generated steps.
- P1: governance looked more concrete, but the first receipt still read like API trace rows.
- P1: architecture was still a card-chain of system modules instead of a user-readable material journey.

Changes landed:

- Replaced public recording terms with user-language copy: `关键时刻`, `步骤草稿`, and `安全试跑`; implementation terms are no longer in the visible primary flow.
- Reweighted the recording demo so the middle generated draft is the larger center object, with human demo and Agent run as supporting previews.
- Converted governance hero and audit receipt from `search_call / inspect_call / delivered_fields / raw_access` to Chinese receipt rows: `搜了什么`, `打开了哪几条`, `交给 Agent 什么`, and `挡住了什么`.
- Rebuilt the architecture main diagram as a material journey: user capture input splits into `完整材料` and `安全文本`, then reaches the Agent boundary with an audit receipt.
- Architecture hero now speaks in user-visible states: `完整截图：本机锁住`, `识别文字：可搜索`, `打开原图：需确认`, `Agent 回答：留账单`.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `./.venv/bin/python -m scripts.audit_static_site --site-dir site/dist`
- Public stale-copy scan returned clean except the intentionally technical CLI JSON demo field `delivered_fields`.
- Desktop screenshots regenerated under `.qa/site-review/`: `active-capture-r19.png`, `architecture-r19.png`, and `governance-r19.png`.

Remaining P2:

- Architecture is now much less module-heavy, but can still be made more editorial with a bespoke animated material path in a later visual pass.
- Recording demo is clearer, but a future pass can animate the key moments physically moving into the draft card for more delight.

Final reviewer follow-up:

- Hooke found no remaining P0/P1 on the r19 screenshots.
- Remaining P2 was limited to lower-detail terminology in the governance receipt and architecture swimlane.
- Governance lower tabs now use user-facing receipt language (`用户问题`, `打开记录`, `实际返回`, `默认决定`) instead of API trace labels.
- Architecture swimlane now uses `完整材料`, `可读文本`, `证据账单`, `完整视频`, `关键时刻`, and `步骤草稿` instead of raw/safe/store terminology.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `./.venv/bin/python -m scripts.audit_static_site --site-dir site/dist`

## 2026-05-31 Reviewer Iteration 21 — Pain-First Homepage And Recording Gate

User feedback after the live preview said the site still felt cluttered, with too many cards/mocks, weak homepage pain framing, and recording animation that did not clearly show the handoff from human demonstration to Agent operation. The user also asked that `Agent` remain the public term.

Reviewer findings:

- P1: Homepage nav order had to keep the story as screenshot first, recording second, Agent third.
- P1: The hero still jumped too quickly to Agent output instead of first explaining the old problem: scattered windows, weak screenshots, and copy-prompt provenance loss.
- P1: Recording demo was too crowded because the human window, WorkRecorder draft, and Agent trial window were all visible with similar weight.
- P1: The safety gate in recording existed as copy, but was not visually strong enough as a user-confirmation step.
- P2: Several labels such as `粗搜 / 精查` still sounded like internal workflow terms.

Changes landed:

- Navigation now reads `首页 / 截图保存 / 记录片段 / 给 Agent 用 / 安全 / 原理`.
- Homepage lead now states the product directly: WorkRecorder is a local context recorder that turns pages, screenshots, and operation snippets into evidence Agent can cite.
- Homepage proof animation was reframed from Agent-answer-first into a three-step failure-to-product story: `材料散落 -> 普通截图 -> WorkRecorder 证据卡`.
- The hero pain bullets now stay concrete: screenshots only keep pixels, recordings are hard to cite, copy-prompt loses provenance, and answers without citations are hard to replay.
- Removed the extra trust-chip row from the hero to reduce visual noise.
- Recording page now states the real sequence in the main proof: `人演示 -> WorkRecorder 整理 -> 用户确认 -> Agent 安全试跑`.
- Recording demo hides the Agent trial window until the confirmed state; the first three states now focus on human demonstration and WorkRecorder's draft.
- Added explicit review actions in the draft card: `修改步骤` and `确认后安全试跑`.
- Removed the duplicate flowline row in the recording demo so the step buttons carry the stage structure by themselves.
- Replaced visible `粗搜 / 精查` labels with user-facing actions such as `找记录 / 打开记录 / 查看`.
- Reduced some heavy label weights and secondary CTA emphasis.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`
- Desktop screenshots generated:
  - `.qa/site-review/home-r22.png`
  - `.qa/site-review/active-capture-r22.png`
  - `.qa/site-review/active-capture-r22-tall.png`

Current visual read:

- Homepage now reads as a product page first: pain, product definition, CTA, then proof demo.
- Recording page has a clearer safety gate and less simultaneous Agent clutter. The demo is still rich, but it now has one primary scene instead of three equal panes at the initial state.
- Remaining polish candidate: the recording page is still visually dense below the fold; future pass could turn the demo into an even more theatrical one-scene animation, but no current P0 is known from this pass.

## 2026-05-31 Reviewer Iteration 22 — Recording Demo Decompression

Follow-up visual review on r22/r23 still saw a P2-to-light-P1 density risk in the recording demo: the initial state was clearer than before, but the WorkRecorder panel still showed future keyframe/draft objects too early, making the demo feel like a UI stack rather than a staged handoff.

Changes landed:

- Recording demo state 0 now shows only the human demonstration window and a simple WorkRecorder status card: `正在观察选中的窗口`.
- Future artifacts are no longer merely dimmed in state 0; they are hidden until the stage needs them.
- State 1 introduces keyframes; state 2 introduces the draft and review actions; state 3 reveals the Agent trial window.
- Added a lightweight live note so the initial WorkRecorder panel does not look empty or broken after removing future-step clutter.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`
- Desktop screenshots generated:
  - `.qa/site-review/home-r24.png`
  - `.qa/site-review/active-capture-r24.png`
  - `.qa/site-review/active-capture-r24-tall.png`

Reviewer status:

- A new strict reviewer pass is running against r24 screenshots to decide whether the remaining density concern is only polish or still blocks the product-story goal.

## 2026-05-31 Reviewer Iteration 23 — Agent Terminology And Recording Confirmation Gate

User feedback asked to keep `Agent` as the public term and continue reviewer-driven cleanup. A fresh reviewer pass reviewed r25 homepage and recording screenshots.

Reviewer findings:

- No P0.
- P1: the recording page was understandable, but the main demo still leaned toward an information panel; the “user confirmation before Agent action” boundary needed to feel more like an explicit gate.
- P1/P2: homepage definition was now clear, but the right proof visual still had several equal-weight boxes; avoid another large restructure and focus on final polish.
- P2: homepage H1 felt slightly heavy against the pearl-glass theme.

Changes landed:

- Removed remaining stale helper wording in current site source and progress language; public navigation and copy now consistently use `Agent`.
- Lowered hero/page H1 weight and size slightly so headings feel less black and less harsh.
- Added a dedicated `用户确认闸门` block to the recording demo draft card.
- The recording demo initial state now explicitly says Agent trial is locked and recording only observes the selected window.
- The confirm button is amber before approval and switches to the safer mint treatment only in the confirmed trial state.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`
- Desktop screenshots generated:
  - `.qa/site-review/home-r26.png`
  - `.qa/site-review/active-capture-r27.png`

Reviewer status:

- Latest reviewer conclusion: no P0; acceptable to start closing after the confirmation-gate polish. Remaining concerns are P2-level density/visual-system refinement, mostly around making the recording animation even more theatrical in a future pass.

## 2026-06-01 Reviewer Iteration 24 — Final Density Reduction

Goal continuation asked to keep pushing toward the original critique: homepage should explain the old screenshot/context shortcomings, Agent should appear after recording, animations should be clearer, and heavy black typography/card density should keep coming down.

Reviewer findings on r28:

- No P0.
- P1/P2: homepage now reads like a product page and explains screenshot/recording/copy-prompt shortcomings, but the right proof demo still felt a bit conceptual rather than fully product-literal.
- P1/P2: recording flow is now understandable and Agent appears after the human demo/confirmation story, but the demo still had too many visible chips/borders.
- P2: black-heavy typography was much improved; no obvious overflow was visible in desktop screenshots.

Changes landed:

- Homepage proof-side step cards were reduced from three equal cards into a lighter vertical cause/effect rail, so the central window carries more of the visual story.
- Recording demo removed the lower duplicate storyboard chips; the top stage control now owns the sequence, reducing one row of visual noise.
- Recording page keeps the explicit `用户确认闸门` and “Agent 试跑被锁住” message in the WorkRecorder panel.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`
- Desktop screenshots generated:
  - `.qa/site-review/home-r28.png`
  - `.qa/site-review/active-capture-r29.png`

Current status:

- Reviewer says no P0 and does not recommend another large rewrite. Remaining risk is P2-level polish: future work can make the recording animation more theatrical and product-literal, but the core story and safety ordering are now in place.

## 2026-06-01 Reviewer Iteration 25 — Remove Remaining P1s

The previous reviewer still found P1 issues: Agent could still feel too early in the story, homepage pain was not yet old-site direct enough, and homepage/recording visuals still felt a bit dense.

Changes landed:

- Homepage H1 no longer makes Agent the first subject. It now says the work scene needs citable evidence; Agent is introduced as a later consumer after capture and confirmation.
- Homepage first-screen contrast changed from four small pain cards to a simpler `以前 / WorkRecorder` comparison.
- The old screenshot/context shortcomings are now spelled out directly: screenshots have only pixels, no source/time/box text/intent; recordings can be replayed but are hard to cite.
- Homepage proof demo moved its three-step explanation into a light lower rail instead of a right-side stack, reducing the “many boxes” feeling.
- Recording demo removed the duplicate stage button row. The page keeps the confirmation proof in the hero and the lock/confirmation gate in the WorkRecorder panel.

Verification:

- `npm --prefix site run check`
- `npm --prefix site run build`
- `python -m scripts.audit_static_site --site-dir site/dist`
- Desktop screenshots generated:
  - `.qa/site-review/home-r31.png`
  - `.qa/site-review/active-capture-r31.png`

Reviewer result:

- No P0.
- No must-fix P1.
- Previous P1s are considered closed: Agent no longer grabs first position, the old screenshot/context shortcomings are direct enough, and the recording page density no longer blocks understanding.
- Remaining comments are P2: homepage proof still looks somewhat conceptual, and future work could replace more mock UI with realistic webpage/PDF/chat fragments.

### Reviewer Iteration 26 - Site story/motion hardening

- Reviewer sweep reopened the site against the active goal: old screenshot/context pain, Agent ordering, animation clarity, cramped density, overflow, and heavy black typography.
- Fixed recording demo state bug: the visible confirm button is no longer counted as a fifth autoplay state; autoplay stops at the draft and does not jump into Agent safe trial without user confirmation.
- Reworded recording hero so the first promise is video/keyframes/step draft; Agent appears only after confirmation.
- Restored the recording flowline as a visible four-step guide and made it follow the current animation state.
- Tightened homepage hero: screenshot and recording shortcomings are now explicit in the first fold, while WorkRecorder is framed as the evidence-card answer before Agent use.
- Reduced homepage demo density by turning the three proof cards into compact progress chips.
- Calmed headline and microcopy weight to reduce the harsh black-title feel.
- Added responsive overrides for state-specific recording grids so narrow screens do not keep the wide two-column layout.
- Verification: `npm --prefix site run check`, `npm --prefix site run build`, and `./.venv/bin/python -m scripts.audit_static_site --site-dir site/dist` passed.
- Visual artifacts: `.qa/site-review/home-r33.png`, `.qa/site-review/active-capture-r32.png`. Latest reviewer pass on r32 reported: no P0/P1/P2 findings, no P1 remains.

### Reviewer Iteration 27 - R35 final density pass

- Generated latest screenshots: `.qa/site-review/home-r34.png`, `.qa/site-review/active-capture-r35.png`.
- Follow-up reviewer reported no P0/P1 on the r34 pass; the only remaining P2 was duplicate keyframe information in the recording draft state.
- Removed the second keyframe row from `RecordingSkillShowcase`; the recording demo now shows keyframes once in the tray and then the step draft, reducing density in the `生成步骤草稿` state.
- Adjusted recording hero proof so it lists three materials first: video replay, keyframes/text, and user-confirmed draft. Agent safe trial is now only described as the post-confirmation outcome.
- Verification: `npm --prefix site run check`, `npm --prefix site run build`, and `./.venv/bin/python -m scripts.audit_static_site --site-dir site/dist` passed.
