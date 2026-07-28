---
work_package_id: WP04
title: The Federation tab, with governed fields shown not offered
dependencies:
- WP03
requirement_refs:
- FR-005
- FR-007
tracker_refs:
- https://github.com/salimfadhley/agent-inbox/issues/15
planning_base_branch: feat/hub-identity
merge_target_branch: feat/hub-identity
branch_strategy: Planning artifacts for this mission were generated on feat/hub-identity. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into feat/hub-identity unless the human explicitly redirects the landing branch.
subtasks:
- T017
- T018
- T019
- T020
- T021
phase: Phase 2 - Surfaces
agent: frontend-freddy
history:
- at: '2026-07-28T14:17:34Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: frontend-freddy
authoritative_surface: src/agent_inbox/console.py
create_intent: []
execution_mode: code_change
owned_files:
- src/agent_inbox/console.py
- tests/test_console.py
role: implementer
tags: []
task_type: implement
---

# Work Package Prompt: WP04 – The Federation tab, with governed fields shown not offered

## ⚡ Do This First: Load Agent Profile

Use the `/ad-hoc-profile-load` skill to load the agent profile specified in the frontmatter
(or any user-defined profile), and behave according to its guidance before parsing the rest
of this prompt.

- **Profile**: `frontend-freddy`
- **Role**: `implementer`
- **Agent/tool**: `frontend-freddy`

If no profile is specified, run `spec-kitty agent profile list` and select the best match
for this work package's `task_type` and `authoritative_surface`.

---

## Markdown Formatting

Wrap HTML/XML tags in backticks: `` `<div>` ``. Use language identifiers in code blocks.

---

## Objectives & Success Criteria

Somewhere to see and edit the three fields — and to be honest about which of them the
operator actually controls.

The tab ships as a **placeholder for federation itself**, on the operator's explicit
instruction: get the settings system working before the feature that needs it, and there
are no non-developer users to confuse. The page should say so plainly rather than implying
federation exists. Peers, modes and blocklists join it later —
`manual-activitypub-federation-v1-01KYJY10` FR-001 already plans that tab.

Complete when:

- The tab renders with all three fields, and the values come from the API rather than being
  recomputed in the console (ADR 0005).
- With an environment variable set, that field is disabled, names the variable, and cannot
  be submitted.
- With nothing set, all three are editable and persist across a restart.
- The page says federation itself is not built yet.
- On an enforcing hub, a caller without an operator session cannot reach the tab's write.

## Context & Constraints

Read before starting:

- `kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/spec.md` — FR-005 and FR-007
- `kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/research.md` — D-08, "governed fields
  are shown, not offered"
- `kitty-specs/a-hub-has-a-name-of-its-own-01KYMD90/contracts/hub-settings.md`
- `src/agent_inbox/console.py` — particularly `_gate` and the existing tab structure

Constraints:

- **The console is a client.** It reads `GET /hub/settings` and writes `PUT /hub`. It does
  not read the environment, and it does not decide what is valid. ADR 0005.
- **Match the existing console.** Same tab mechanism, same styling, same `_gate` posture.
  Do not introduce a framework, a build step, or a second way of rendering a form.
- **Do not offer a control that does nothing.** An editable field that silently loses its
  value on restart is the same family as a check that passes with nothing to look at, or a
  send that succeeds and reaches nobody. It looks like it worked.

## Branch Strategy

- **Strategy**: Planning artifacts for this mission were generated on `main`. During
  `/spec-kitty.implement` this WP may branch from a dependency-specific base, but completed
  changes must merge back into `main` unless the human explicitly redirects the landing
  branch.
- **Planning base branch**: `main`
- **Merge target branch**: `main`

Execution worktrees are allocated per computed lane from `lanes.json`; do not create one by
hand. Assert the branch and `HEAD` before any commit.

Implementation command (depends on WP03):

```bash
spec-kitty agent action implement WP04 --agent <name>
```

## Subtasks & Detailed Guidance

### T017 — A Federation tab and its navigation entry

- **Purpose**: a home for hub identity, and later for federation itself.
- **Files**: `src/agent_inbox/console.py`
- **Steps**:
  1. Add the tab alongside the existing ones, using whatever mechanism they already use.
     Consistency with the existing console matters more than any improvement to it.
  2. Apply `_gate` exactly as the neighbouring tabs do. Where the hub authenticates, an
     operator session is required; where it does not, the console is already open and this
     changes nothing.
  3. Include a short, plain notice that federation itself is not built yet and that this tab
     currently holds the hub's identity. Say what it is, not what it will be — a page that
     promises federation is a page that lies until the federation mission lands.

### T018 — Render the three fields from the API

- **Purpose**: one source of truth, and it is not the console.
- **Files**: `src/agent_inbox/console.py`
- **Steps**:
  1. Fetch `GET /hub/settings`. Render `name`, `title` and `description` from the `value` it
     returns.
  2. Do not read environment variables in the console, and do not reconstruct the precedence
     rule here. If the console computes which source won, there are two implementations of
     one rule and they will disagree.
  3. An unset `title` or `description` arrives as `"value": null` with `"source":
     "default"`. Render it as an empty field — never as the string `"None"`, and never as
     the word "default". Both are unset on every hub today, so this is the common rendering,
     not the edge case.
  4. A field an operator deliberately cleared arrives as `stored` with an empty value. It
     also renders empty. The two look the same to the operator and that is correct; what
     matters is that the console does not turn one into the other on submit.
  5. Label the fields so the distinction the mission exists to make is visible: `name` is
     the `@hub` part of an address; `title` is a display name; `description` is prose. The
     public URL is **not** on this page — it is an address, set by the deployment, and
     putting it here would re-conflate the two things being separated.

### T019 — Governed fields render disabled, naming the variable

- **Purpose**: a disabled field must read as governed, not as broken.
- **Files**: `src/agent_inbox/console.py`
- **Steps**:
  1. Where `source` is `environment`, render the input disabled.
  2. Beside it, state that the deployment sets this value and **name the variable** from the
     response's `variable` field. "`AGENT_INBOX_HUB_NAME` is set by this deployment" reads
     as governed; a greyed box with no explanation reads as a bug, and the operator files it
     as one.
  3. Use the variable name the API reports, not a hardcoded string. A deployment configured
     through the legacy `AGENT_MAILBOX_` prefix must be told about the variable actually in
     effect, or the operator edits the wrong one and concludes the console is broken.
  4. Where `source` is `stored` or `default`, the field is editable and no notice appears.

### T020 — Submit through `PUT /hub`, and surface refusals

- **Purpose**: an operator who is refused should learn why.
- **Files**: `src/agent_inbox/console.py`
- **Steps**:
  1. Submit changed fields to `PUT /hub`. Send only what changed; the route accepts partial
     bodies.
  2. On `422`, show the validator's message — it names the rule, and the operator needs to
     learn it. Do not replace it with a generic "invalid input".
  3. On `409`, show the message naming the governing variable. This should be unreachable
     from the UI because T019 disabled the field, which is exactly why it must be handled: a
     `409` arriving here means the page's state and the hub's disagree, and silently
     swallowing it would hide that.
  4. On success, re-render from the API's returned resolved state rather than from what was
     submitted. They differ whenever the environment governs, and showing the submitted
     value would tell the operator a change took effect when it did not.

### T021 — Console tests

- **Purpose**: pin the rendering decisions that carry the argument.
- **Files**: `tests/test_console.py`
- **Steps**:
  1. The tab renders, and the three fields appear with values from the API.
  2. **With `AGENT_INBOX_HUB_NAME` set**: the name field is disabled *and* the variable name
     appears in the rendered page. Assert both — a disabled field with no explanation is the
     failure this subtask exists to prevent, and asserting only `disabled` would pass.
  3. With nothing set: all three are editable, and no governance notice appears.
  4. The placeholder notice about federation appears.
  5. On an enforcing hub without an operator session, the tab's write is unreachable —
     matching `_gate`'s existing behaviour on neighbouring tabs.
  6. A round trip: submit a title, and assert it comes back from `GET /` on the next render.
- **Establish the premise**: in test 2, set the variable and assert the API reports
  `source: environment` before asserting the console disables the field. Otherwise a console
  that disables everything passes.

## Test Strategy

Litestar's `TestClient` against the console app, as `tests/test_console.py` already does.
Assert on rendered content, not on internal state — the operator sees the page.

Note the trap this repo has hit: four console tests once pinned `agent-mailbox.toml` after
a rename made it `agent-inbox.toml`. When a test asserts on a literal string, ask whether
the string or the intent is the thing being guarded.

## Definition of Done

- [ ] A Federation tab exists, gated as its neighbours are.
- [ ] Three fields render from `GET /hub/settings`.
- [ ] The public URL is not on this page.
- [ ] Governed fields are disabled and name the variable the API reports.
- [ ] Submitting writes through `PUT /hub`; `409` and `422` are surfaced with their
      messages.
- [ ] Success re-renders from the resolved state, not from the submission.
- [ ] The page says federation itself is not built yet.
- [ ] Tests assert both `disabled` and the variable name.
- [ ] All four charter gates pass: `uv run pytest`, `uv run ruff check`,
      `uv run ruff format --check`, `uv run pyright`.

## Risks

| Risk | Why it bites | Mitigation |
|---|---|---|
| A disabled field with no explanation | Reads as broken; gets filed as a bug | T019 step 2; T021 asserts the variable name |
| Console recomputing precedence | Two implementations of one rule, diverging | T018 step 2 |
| Hardcoding the variable name | Wrong for legacy-prefix deployments | T019 step 3 |
| Re-rendering the submitted value | Tells the operator a change took effect when it did not | T020 step 4 |
| Putting the public URL on the page | Re-conflates address and identity | T018 step 4 |
| A page implying federation works | It does not, and someone will believe it | T017 step 3 |

## Reviewer Guidance

- Set the environment variable and load the page. If the field is grey and says nothing,
  the package has failed at its main job regardless of what the tests say.
- Check the test asserts the variable name appears, not merely that the input is disabled.
- Check nothing in `console.py` reads `os.environ` for these three values.
