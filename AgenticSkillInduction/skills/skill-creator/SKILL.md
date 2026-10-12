---
name: skill-creator
description: Create self-contained, operationally complete NexAU skills from inspected computer-use benchmark evidence. Use when an extractor must convert task instructions, action traces, screenshots, and video observations into portable skill folders without copying episode-specific details.
---

# Create Reusable NexAU Skills

Convert observed task behavior into instructions that another NexAU agent can
execute with fresh task inputs. Describe stable decisions, semantic targets,
visible state, completion checks, and supported recovery rather than replaying
the recorded trajectory. This Skill is the authoring policy for generated
Skills; do not replace its requirements with a shorter summary.

## Runtime Contract

The execution agent receives the generated Skill and its bundled resources,
not the source recording, action trace, or extraction manifest. Put every
correctness-critical instruction in `SKILL.md`; supporting references must not
be required to reconstruct an omitted workflow, formula, selection rule,
quantity, ordering constraint, stop condition, or completion check.

For a graphical computer-use task, preserve the interaction modality. Instruct
the agent to make task-state changes through visible application controls and
verify them in the visible application. Never substitute an API, database edit,
script, browser console, developer tool, or other hidden state mutation unless
the authoritative task explicitly requires that mechanism.

Length is not a quality target. Remove generic explanation and trace
provenance, not operational invariants. If removing a detail could change the
selected target, computed value, action order, affected quantity, visible
success state, or recovery behavior, retain it.

## Define the Skill Boundary

Create one Skill for each coherent reusable capability. Keep phases together
when they exchange task-derived data, share application state or counts, or
must execute in a particular order. Split Skills only when each capability is
independently invocable and useful; do not fragment one workflow merely to make
individual files shorter.

Choose a short lowercase hyphen-case name under 64 characters. Use the same
name for the output folder and the frontmatter `name`.

## Separate Procedure from Trace

Treat the task instruction as the goal and the recording as fallible evidence.
Read the task first, then reconcile task data, action logs, evidence images,
and video before stating the reusable procedure. Recording completion alone
does not prove task success.

A recorded state change demonstrates interface mechanics but does not authorize
an extra persistent mutation. Preserve only state changes required by the task,
and retain:

- semantic application, page, dialog, field, item, and control names;
- rules for choosing the correct target from changing task inputs;
- exact formulas, operands, units, basis, thresholds, rounding rules, and where
  each computed result is used;
- requested quantities and scope, including per-item repetition and count-based
  stop conditions;
- dependencies, required order, and data or state passed between phases;
- visible checks after critical mutations and a final observable completion
  check, including refresh or reopen checks when persistence matters;
- evidence-supported recovery from loading delays, stale searches, hidden
  controls, misclicks, dialogs, validation errors, and partial completion.

Remove screen coordinates, action indexes, timestamps, session identifiers,
local machine paths, and retries or idle actions that do not teach recovery.
Replace one episode's names, dates, IDs, routes, values, filenames, and messages
with task-derived parameters when they are inputs rather than reusable
constants.

Parameterize episode-specific values without abstracting away the formula,
threshold, relationship between inputs, requested count, ordering constraint,
selection rule, or visible verification that makes the procedure correct. Do
not promote one observed layout, value, or incidental action into a universal
requirement.

When evidence is incomplete, state an observable conditional check or supported
limitation in the Skill. Never invent a hidden rubric or success condition.

## Write the Skill

Create `<skill-name>/SKILL.md` with `write_file`. Start with exactly this
frontmatter shape:

```yaml
---
name: skill-name
description: Explain what the skill does and the situations that should trigger it.
---
```

Write the body in clear imperative language. Include the complete workflow,
selection and calculation rules, scope and count constraints, phase handoffs,
visible completion checks, and only recovery guidance supported by evidence.
Avoid introductory material a capable execution agent already knows, but never
remove a step, dependency, decision, stop condition, or recovery check that can
affect correctness.

Use semantic UI targets instead of fixed coordinates. When labels or layouts
may vary, give a stable visible role or relationship that identifies the target
without guessing. For persistent changes, verify the resulting visible state;
refresh, revisit, or reopen the relevant view when the observed workflow shows
that this is necessary to distinguish a saved result from a transient one.

Add `references/` only for genuinely supporting knowledge, never as a place to
hide required runtime instructions. Add `scripts/` or `assets/` only when they
are essential to reuse and their correctness can be established from the
available evidence. Do not initialize templates, run packaging scripts, or
create archives.

## Self-Review

Before finalization, read every final `SKILL.md` back with `read_file` after its
last write and verify:

- the folder name and frontmatter name match, the description identifies the
  right trigger, and the body is non-empty;
- an execution agent can complete the workflow without the source recording,
  trace, extraction manifest, or unstated episode knowledge;
- graphical tasks make state changes through visible UI actions and do not
  offer backend or developer shortcuts unless the task explicitly requires one;
- every explicit goal, formula, operand, unit, quantity, scope, selection rule,
  ordering relationship, phase handoff, and count-based stop condition needed
  at runtime is present;
- semantic targets replace coordinates and incidental layout;
- critical mutations and the final result have observable UI checks, including
  persistence checks where required;
- every instructed persistent mutation is authorized by the task;
- supported failure modes retain their recovery and stop conditions;
- episode-specific values are parameterized without erasing the relationships
  that govern their use;
- material uncertainty is an observable conditional check or limitation, not an
  invented action or hidden success criterion;
- every bundled file is referenced, necessary, and contains no core instruction
  that belongs in `SKILL.md`.

Call `finalize_extraction`. The runtime writes the extraction manifest. Treat
the finalizer result as authoritative: correct every reported issue and call it
again. Do not finish with an ordinary text response.
