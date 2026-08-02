# Implementation Plan: shared tokens only

**Branch**: `main` | **Date**: 2026-08-02 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `kitty-specs/shared-tokens-only-01KYG7S7/spec.md`

**Branch contract**: planning happens on `main`, the base is `main`, and completed
changes merge into `main`. `branch_matches_target` is true.

## Summary

One kind of credential. A token admits a **machine**; the agent's name arrives separately
in `X-Agent-Name` and is settled by the hub exactly as it is today. Every token is listed,
labelled, revocable, and carries the agents it has actually admitted — so revoking is an
informed act rather than a guess.

The work is smaller than the spec's twelve requirements suggest, because most of the
machinery exists. `auth_device_tokens` already has `label`, `created`, `last_used` and
`revoked`. `resolve_token` already refuses revoked tokens. The console already mints, shows
once, and copies. What is missing is: a table recording which agent a token admitted, one
screen that lists tokens rather than agents, three API routes in place of three others, and
prose in six places that stops describing a shape we no longer have.

## Technical Context

**Language/Version**: Python 3.14
**Primary Dependencies**: Litestar 2.24, msgspec, aiosqlite; no new dependency
**Storage**: SQLite — `auth_device_tokens` (exists), `auth_token_use` (new)
**Testing**: pytest. `tests/test_auth_service.py`, `tests/test_auth_store.py`,
`tests/test_auth_api.py`, `tests/test_console.py` are rewritten, not deleted — the
properties they pin (operator-only, shown once, revocation refuses) all still hold
**Target Platform**: the hub, as a container and as `agent-inbox serve`
**Project Type**: single package, `src/agent_inbox`
**Performance Goals**: authentication must not get slower. It currently writes once per
authenticated request; after this it writes at most once per token per bucket
**Constraints**: no lockout on upgrade (FR-006); no per-agent token creatable by any path
**Scale/Scope**: single-owner hub, a handful of machines, tens of agents

## What the code says today, checked rather than assumed

Four findings from reading the source before planning. Each changes an estimate.

**1. `resolve_token` has exactly one production caller.** `api.py:1483`, inside
`resolve_verified_caller`, plus three references in `tests/test_auth_service.py`. The spec
calls the signature change "the shape problem"; it is a contained one.

**2. Authentication already writes on every call.** `resolve_token` calls
`touch_token(token.id, now)` — an `UPDATE` plus a `commit` — for every successful
authentication. FR-009's coarse recording is therefore a **reduction** in hot-path writes,
not an addition, and the existing `last_used` write folds into the same bucket. The spec has
been corrected; this plan takes the corrected reading.

**3. Schema growth is additive and already provided for.** Tables are created with
`CREATE TABLE IF NOT EXISTS` from a `_SCHEMA` tuple at open; there is no migration
framework and none is needed. `auth_token_use` is one more entry in that tuple.

**4. The identity rule genuinely does not move.** `provide_caller` already returns
`caller_name(request)` — the header — when the resolved caller is `SHARED_ACTOR`. Making
every token shared widens a path that already exists rather than adding one.

## Charter Check

| Directive | Standing |
|---|---|
| Four gates (`pytest`, `ruff check`, `ruff format --check`, `pyright`) | Every work package |
| DIR-004 — outside model review before a package closes | One narrow question per package |
| Ship early, ship often | Each package released and deployed to **both** hubs before the next starts |
| No deployment specifics in the repo | Nothing here names a host; token values never leave the browser or the hub |
| ADR 0005 — one API, every client is a client | The console gets no security judgement; the operator gate stays on the API routes |
| ADR 0008 — no actor has authority over the mailbox | FR-012 exists because of it |

No conflicts. FR-012 is the charter arriving at a feature shipped two days ago rather than a
new tension.

## Phase 0 — the questions worth settling before writing code

**Bucket size for coarse last-use recording (FR-009).** Chosen: **one minute**, held in
memory per process. Fine-grained enough that "last used" reads as live during setup — which
is when an operator actually stares at the screen — and coarse enough to collapse a busy
agent's traffic to a single write. A minute also survives the restart story without special
handling: the cache is per process, so a restart writes once more than it needed to and
nothing is lost.

**Do bound tokens exist in the wild?** Unverified, and deliberately not blocked on. FR-006
is built as specified regardless: the cost is a display marker and a branch that keeps old
rows working, and the cost of being wrong the other way is an operator locked out of their
own hub by an upgrade. Asymmetric, so build it.

**What replaces `resolve_token`'s return value?** The token record, rather than an actor.
The caller — `resolve_verified_caller` — already knows the claimed name from the header and
is the right place to combine the two, because it is where "who is this" is decided for
every route. `resolve_token` answers "is this credential good", which is the only question a
secret can answer.

## Phase 1 — design

### Data model

```
auth_token_use
  token_id    TEXT NOT NULL      -- auth_device_tokens.id
  actor       TEXT NOT NULL      -- the name claimed on the admitted request
  first_seen  TEXT NOT NULL
  last_seen   TEXT NOT NULL
  uses        INTEGER NOT NULL DEFAULT 0
  PRIMARY KEY (token_id, actor)
```

Upserted on authentication. One row per agent-token pair: bounded by the number of agents
no matter how much traffic flows (FR-011). The cost, accepted in the spec: no history — you
can see that an agent last used a token on Tuesday, not that it used it heavily in June.

`uses` is a counter, not a log, and exists so that "used twice" and "used ten thousand
times" are distinguishable. Under bucketing it counts **buckets**, not requests, and the
column comment must say so — a number that looks like a request count and is not is worse
than no number at all.

### API

| Route | Method | Who | Replaces |
|---|---|---|---|
| `/auth/tokens` | `POST` | operator | `POST /auth/agents/{name}/tokens` |
| `/auth/tokens` | `GET` | operator | `GET /auth/agents/{name}/tokens` |
| `/auth/tokens/{token_id}` | `DELETE` | operator | `DELETE /auth/agents/{name}/tokens/{id}` |

`POST` takes `{"label": "…"}` and **refuses an empty label** (FR-002). `GET` returns, per
token: `id`, `label`, `created`, `lastUsed`, `revoked`, `boundTo` (null for shared, a name
for a legacy row), and `admitted` — a list of `{name, firstSeen, lastSeen, uses}`, most
recent first.

The three old routes are **removed**, not deprecated. This is a single-owner hub with one
console and one CLI, both shipped from this repository; leaving a second way to mint is the
thing the mission exists to stop.

### Console

`/tokens` becomes one screen listing every token: label, issued, last used, admitted
agents, Revoke. `/tokens/{name}` and the Agents directory's Tokens column go away.

Two columns that must not merge (FR-010): **Issued to** is a claim the operator typed;
**Admitted** is what the hub observed. A stale label sitting where a fact appears to be is
how an operator revokes the wrong credential.

### The prose (FR-007 and FR-012), six places

`prompts.py` (the device-token paragraph), `cli.py` `_token_help`, the MCP `join` tool's
`token` parameter, `README.md`, the Tokens page's own text, and
`doc/interrupting-an-agent.md`, whose table has a row for per-agent device tokens that will
no longer exist.

## Implementation Concern Map

| IC | Concern | Where |
|---|---|---|
| IC-01 | Recording which agent a token admitted, cheaply and boundedly | `auth/store.py`, `auth/records.py`, `auth/service.py` |
| IC-02 | One credential shape: mint, resolve, and the legacy row that must keep working | `auth/service.py`, `api.py` |
| IC-03 | Three routes in, three out | `api.py` |
| IC-04 | One screen that lists tokens rather than agents | `console.py` |
| IC-05 | The words follow the code, in six files | `prompts.py`, `cli.py`, `mcp_client.py`, `README.md`, `console.py`, `doc/` |

IC-01 and IC-02 belong in one package: the usage table is written from the resolve path, and
splitting them means shipping a table nothing writes to. IC-03 depends on both, IC-04 on
IC-03. IC-05 follows and must not lead — prose describing behaviour that has not shipped is
a failure this project keeps finding.

## Risks

**The hot path.** Authentication is the most-called code here and this mission puts an
upsert on it. Bucketing is what keeps that honest, and the bucket must be checked *before*
the write rather than the write made conditional after the fact.

**FR-006 is where a lockout hides.** A legacy bound token must keep authenticating its
agent. The test that matters is not "a bound token is listed" but "a bound token still lets
its agent in", and it should be written first.

**Revocation must stay immediate.** It already is — `resolve_token` raises `TokenRevoked`
before anything else — and the refactor must not move that check behind the new usage write.

## What this plan does not do

No expiry, no rotation, no scopes. No change to how an agent sends a token, or to the human
login model. Failed authentication attempts are explicitly out of scope and filed
separately: they are driven by unauthenticated callers, have a different retention story,
and deserve a hub-wide treatment rather than a corner of a token screen.
