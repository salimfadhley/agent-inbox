# Tasks: Retry delivery to a sleeping peer

**Mission**: `retry-delivery-to-a-sleeping-peer-01KYWFWB`
**Spec**: [spec.md](spec.md) · **Plan**: [plan.md](plan.md)
**Branch**: `kitty/mission-retry-delivery-to-a-sleeping-peer`

Three work packages, strictly sequential. They are sequential because each one's *tests*
need the previous one's behaviour to exist — not merely its types — and a parallel split
here would buy nothing but merge conflicts in one file.

| WP | Goal | Depends on |
|---|---|---|
| WP01 | The third state, and the regression it would otherwise cause | — |
| WP02 | Retrying delivery: classify the failure, retry only the world | WP01 |
| WP03 | Wiring, lifecycle, and where the outcome is visible | WP02 |

## Subtask index

| ID | Description | WP | Parallel |
|---|---|---|---|
| T001 | `Receipt.queued` and the third `state` word | WP01 | |
| T002 | Correct `Sent.reached_nobody` so queued is not "nobody" | WP01 | |
| T003 | Tests for the three states and the corrected guard | WP01 | |
| T004 | Retire the "Step 7 adds this" docstrings now that it has | WP01 | |
| T016 | A queued receipt discloses that the queue is not durable | WP01 | |
| T005 | `Queued` signal and the failure taxonomy | WP02 | |
| T006 | `RetryingDelivery` wrapper: attempt once, classify | WP02 | |
| T007 | The retry loop with bounded backoff | WP02 | |
| T008 | Terminal on refusal — the removal proof for FR-004 | WP02 | |
| T009 | Re-derived authorization — the removal proof for FR-002/005 | WP02 | |
| T010 | Backoff and bound tests without real waiting | WP02 | |
| T011 | Build the queue into `House` | WP03 | |
| T012 | Fail outstanding deliveries on close (FR-008) | WP03 | |
| T013 | `@local` never enters the queue — removal proof for FR-007 | WP03 | |
| T014 | Audit-log the outcome | WP03 | |
| T015 | Does our own inbox de-duplicate a retried activity? | WP03 | |
| T017 | Outside model review before the mission closes (Directive 4) | WP03 | |

*(T016 belongs to WP01 and T017 to WP03; both were added after analysis, hence the
out-of-order ids. T016 came from finding A2, T017 from C1 — the charter directive the
first analysis pass missed because it never read the charter.)*

---

## WP01 — The third state, and the regression it would otherwise cause

**Goal**: `Receipt` can say `queued`, and nothing that currently reads receipts draws the
wrong conclusion from it.
**Priority**: foundational — everything else depends on the vocabulary.
**Independent test**: construct a queued receipt; the send does not report reaching nobody.

- [x] T001 `Receipt.queued` and the third `state` word (WP01)
- [x] T002 Correct `Sent.reached_nobody` so queued is not "nobody" (WP01)
- [x] T003 Tests for the three states and the corrected guard (WP01)
- [x] T004 Retire the "Step 7 adds this" docstrings now that it has (WP01)
- [x] T016 A queued receipt discloses that the queue is not durable (WP01)

**Why this is its own package**: T002 is a *correction to existing correct code*, and it is
the one change in this mission that can silently break something that works today. Isolating
it means the diff that changes `reached_nobody` is small enough to be read carefully.

**Risks**: `reached_nobody` feeds `api.py`'s refusal to return 201 for a send that reached
nobody. Getting it wrong in the other direction — reporting success for a send that truly
reached nobody — is worse than the bug being fixed.

---

## WP02 — Retrying delivery: classify the failure, retry only the world

**Goal**: an unreachable peer is retried with bounded backoff; a refusal never is.
**Priority**: the mission.
**Independent test**: a delivery that fails twice then succeeds arrives, without the caller
waiting for it.

- [ ] T005 `Queued` signal and the failure taxonomy (WP02)
- [ ] T006 `RetryingDelivery` wrapper: attempt once, classify (WP02)
- [ ] T007 The retry loop with bounded backoff (WP02)
- [ ] T008 Terminal on refusal — the removal proof for FR-004 (WP02)
- [ ] T009 Re-derived authorization — the removal proof for FR-002/005 (WP02)
- [ ] T010 Backoff and bound tests without real waiting (WP02)

**Why a new module**: `RetryingDelivery` lives in `src/agent_inbox/retry.py`, not in
`delivery.py`. It keeps WP01's ownership clean, and it keeps the *policy* of retrying
separate from the *mechanism* of federated delivery — the same separation that let
`deployment.py` know nothing about how anything is deployed.

**Risks**: the whole mission's safety property lives in T009. A queue that caches an
authorization decision is the defect the parent spec's FR-050 was raised to prevent, and it
would pass every happy-path test.

---

## WP03 — Wiring, lifecycle, and where the outcome is visible

**Goal**: the queue is part of a running hub, stops honestly when the hub does, and leaves
a trace an operator can read.
**Priority**: completes the slice.
**Independent test**: close a `House` with a message queued; the message is failed, not
silently dropped.

- [ ] T011 Build the queue into `House` (WP03)
- [ ] T012 Fail outstanding deliveries on close (FR-008) (WP03)
- [ ] T013 `@local` never enters the queue — removal proof for FR-007 (WP03)
- [ ] T014 Audit-log the outcome (WP03)
- [ ] T015 Does our own inbox de-duplicate a retried activity? (WP03)
- [ ] T017 Outside model review before the mission closes (Directive 4) (WP03)

**Risks**: T012 is what makes the in-memory queue (C-001) acceptable rather than
irresponsible. Without it a sender is told `queued` and the promise evaporates at the next
deploy — which we do on every release.

T015 may find a defect in the *receiving* half. If it does, that is a new issue, not extra
scope here.

---

## MVP scope

**WP01 + WP02 are the feature.** WP03 is what makes it honest. Shipping WP01+WP02 without
WP03 would give a hub that retries but lies at shutdown, so the slice is all three — but if
the mission must be cut short, WP03's T012 matters more than T014 or T015.

## Parallelisation

None. Three packages, one lane, each depending on the last. Splitting for parallelism here
would mean two agents editing the delivery path at once for no wall-clock gain on a change
this size.
