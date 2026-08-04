# Implementation Plan: Federated identity and trust

**Branch**: `main` | **Date**: 2026-08-04 | **Spec**: `kitty-specs/federated-identity-and-trust-01KYN49V/spec.md`

## Summary

Most of this mission's spec is already running. The plan is therefore mostly an **audit
result**: which of its 24 requirements are shipped, which are not, and a build order for
the remainder. Planning it as written would schedule work that landed weeks ago.

What is genuinely missing is the *identity and visibility* half — the blocklist, actor
visibility, the server descriptor, the operator's CLI, and audit of federation
administration. That is a coherent mission on its own and it is what this plans.

## This mission supersedes two orphaned packages of its parent

`manual-activitypub-federation-v1-01KYJY10` has fourteen work packages. Twelve landed. The
two that did not are **WP03 "the policy decision"** and **WP10 "actor visibility"** — and
they are the same work as this mission's FR-004/FR-006/C-006 and FR-012/FR-014/FR-015/
FR-016 respectively, written twice because this mission was carved out of that one.

**They must not both be implemented.** The parent's WP03 says it plainly: *"if the decision
is made in two places they will disagree, and a disagreement here is a disclosure"* — and
building it from two work packages is the most direct route to exactly that. This mission
is the one that gets built; the parent's WP03 and WP10 are marked superseded.

## The audit — checked in the code, not assumed

Every row below was verified by reading the source on 2026-08-04.

### Already shipped — do not rebuild

| Req | Evidence |
|---|---|
| FR-001 federation off by default | `hub_settings.py:57` — `"federation": "disabled"` |
| FR-002 cannot enable without a URL and a non-`local` name | `check_may_enable_federation()`, called at `api.py:469` |
| FR-005 `https` only, by allowlist | `peers.py:42` — `ALLOWED_SCHEMES = ("https",)`, with a comment on why a denylist is a guess |
| FR-007 peer add flow (except the blocklist step) | `peers.py` — normalise, fetch, check, report |
| FR-011 WebFinger | `api.py:549`, host-checked at `:574` |
| FR-018 signing keypair | `keys.py` — `generate`, `sign`, `verify`, `public_pem` |
| FR-019 settings precedence | `hub_settings.py`, environment wins for scalars |
| NFR-002 two hubs without sockets | `tests/federation/harness.py`, `test_two_real_hubs.py` |

### Not built — this mission's actual scope

| Req | What is there today |
|---|---|
| **FR-004 blocklist** | **Nothing.** "blocklist" appears nowhere in `src/`. The only way to refuse a peer is not to add it, which FR-004 explicitly says is not the same thing |
| **FR-012 `local` actors must not resolve** | No visibility concept exists, so nothing can be withheld |
| **FR-014 directory lists `discoverable` only** | `House.directory()` returns **every actor**, unfiltered (`house.py:448`). `/actors` is guarded by `guard_enforce`, so it is not open to the world — but there is no per-actor filter beneath it |
| **FR-015 visibility as a profile field** | `discoverable` appears nowhere |
| **FR-016 visibility is a ceiling, never a grant** | Nothing to be a ceiling on yet |
| **FR-009 `/.well-known/agent-inbox` descriptor** | Only `/.well-known/nodeinfo` and `/.well-known/webfinger` exist (`api.py:1741`, `:1750`) |
| **FR-022 the operator CLI** | No federation or peer commands in `cli.py` |
| **FR-023 audit of federation administration** | `Attempt`/`Outcome` exist for messaging; federation admin actions are not audited |

### Verify at implementation time

**FR-020** — the spec says the federation inbox must stop answering `501` and stop citing
missions 0024/0025. Neither `501` nor those numbers appear in `api.py` today, so this may
already be fixed. Confirm before writing anything; a requirement satisfied before you start
should be closed, not re-satisfied.

## Technical Context

**Language/Version**: Python 3.14
**Primary Dependencies**: none new. `cryptography` (already present, for `keys.py`), Litestar,
click. The blocklist and visibility are stored state, not a library.
**Storage**: SQLite. One new stored list (the blocklist) and one new actor field
(visibility). Peer lists and the blocklist are **stored-only** — decision
`01KYMQ6PTT9J16PCA5H8FF66QX`: precedence applies to scalars, lists have no environment
equivalent.
**Testing**: pytest, with `tests/federation/harness.py`'s two-hubs-in-one-process rig, which
already exists and needs no socket. Disclosure requirements are asserted as **absences**
(NFR-004): a test that checks a field is present cannot catch a field that should not be.
**Target Platform**: the hub container.
**Project Type**: single package, `src/agent_inbox/`.
**Performance Goals**: none specific. The blocklist is consulted before any network call, so
it must be a local lookup, not a fetch.
**Constraints**: the policy decision is made in exactly one place (C-006); `@local` never
federates (C-002); no name registry (#16 stays deferred); CLI is the operator surface, the
console is a later mission.
**Scale/Scope**: `peers.py`, `mailbox.py`, `house.py`, `api.py`, `cli.py`, `vocabulary.py`,
plus tests. No new module unless the policy decision earns one.

## The design decisions

### 1. The blocklist is consulted before the network, and it is not a mode

FR-004 and the test matrix are explicit: *"A blocked domain in `allowlist` mode → refused,
**and no network call made**"*. So the check is the first step of the add flow, before
`peers.fetch_descriptor` — otherwise blocking somebody still tells them we tried, and a
blocklist that leaks a request to the party it blocks is worse than none.

Matching normalises case, trailing slash and default port, because FR-004 says so and
because those three are how a blocklist is trivially evaded by accident.

### 2. Visibility is a profile field the actor sets, and a ceiling the hub enforces

`local` / `normal` / `discoverable`, default `normal`, written through the existing
`update_profile` surface — decision `01KYMQ8T23YB16YY7Y88EZPVVD`, selected because Lemmy
lets users control their own discoverability and because a second place for actor facts is
a second place for them to disagree.

**It is a ceiling, never a grant** (FR-016). A `discoverable` actor on a `disabled` hub is
unreachable; server policy still wins. The order of evaluation is: hub mode, then blocklist,
then visibility — and if any refuses, the answer is the same refusal, because a differently
worded refusal is an oracle.

**FR-012 is the sharp one.** A `local` actor must not resolve *at all* — not through
WebFinger, not in the directory, not by document lookup. A 404 that differs from the 404 for
a name nobody has ever held is itself the disclosure. This is the requirement most likely to
be implemented as a filter on the directory alone and called done.

### 3. One decision function, and the tests prove there is only one

C-006, and the parent's WP03 called it the highest-value target in that mission. A single
function answers *may this exchange happen*; every inbound and outbound path asks it and
none re-derives it. The test that matters is not that it returns the right answer — it is
that no second implementation exists.

### 4. The CLI is the operator surface, and it computes nothing

FR-022 and NFR-003. Enable/disable, peers add/remove/list, blocklist add/remove/list, and a
status view naming which settings the environment has fixed — the pattern `config list`
already uses. The CLI reads and writes through the API and recomputes no policy, or C-006 is
broken from the client side.

## Phase 0 — research

None required. The mission's own spec records every open question as answered on 2026-07-28
with decision ids, and the audit above replaced the only genuinely unknown thing — what is
already built. `research.md` is deliberately not generated.

## Work split

**Ship 1 — refusal.** The blocklist, the single decision function, and the add-flow
ordering. Coherent alone: an operator gains the ability to refuse a peer, which is the
concrete safety gap.

**Ship 2 — visibility.** The actor field, the three levels, the directory filter, and
FR-012's "does not resolve at all". The larger and more delicate half.

**Ship 3 — the surfaces.** The `/.well-known/agent-inbox` descriptor, the operator CLI, and
federation audit entries.

Each ships and deploys before the next starts.
