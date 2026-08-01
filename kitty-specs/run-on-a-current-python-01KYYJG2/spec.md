# Spec — Run on a current Python

- Mission: `run-on-a-current-python-01KYYJG2`
- Supersedes issue **#13**, which says "migrate to Python 3.13". See below — that target is
  now stale.
- Status: **draft for discussion.** Deliberately unhurried: blocks nothing, blocked by nothing.

## The target is 3.14, not 3.13

The issue was filed when 3.13 was current. It is not.

| Available | Note |
|---|---|
| 3.13.11 | Deep maintenance — an eleventh patch release |
| **3.14.2** | Settled, with two patch releases behind it. **The target.** |
| 3.15.0 | Brand new. Dependency wheels usually lag a `.0` by months |

Moving to 3.13 would be migrating onto a version already two releases behind, and would leave
this same mission to be run again. **3.14 is the current release that is actually finished.**

3.15 is the wrong bet today for one reason only: this project has ten-odd dependencies, and a
`.0` is where wheels are missing and native builds break. Worth revisiting once 3.15.2 exists.

## Why do this at all

The floor is `>=3.12` and the interpreter in use is 3.12.1.

**This is not a library.** It is installed as a tool that brings its own interpreter, so it
owes nobody multi-version support, and an old floor buys nothing but old language. That is the
operator's call, recorded 2026-08-01, and it is what makes this cheap.

## What 3.13 and 3.14 actually give *this* codebase

Not a general feature list — the things that touch code we have.

| Feature | Where it lands here |
|---|---|
| **PEP 649 — deferred annotations by default** (3.14) | **The biggest single win.** Every module in `src/agent_inbox/` opens with `from __future__ import annotations`. In 3.14 that is the default, so those lines become noise to be removed. Dozens of files, mechanical, and it removes a thing every new reader has to explain to themselves. |
| **`copy.replace()`** (3.13) | This codebase is built on frozen slotted dataclasses — `Receipt`, `Sent`, `ObjectRecord`, `PeerIdentity`. `copy.replace()` is the standard-library answer to "one field different", which we currently write by hand. |
| **`typing.TypeIs`** (3.13) | Real narrowing where we currently write `assert isinstance(resolved, outbound.RemoteRecipient)` — see `delivery.py`, which does exactly that twice to satisfy a `Protocol` boundary. |
| **asyncio improvements** (3.14) | The hub is asyncio throughout, including a retry queue that spawns a task per queued delivery. Better introspection is directly useful when something hangs. |
| **Better error messages** (both) | Costs nothing, helps every debugging session. |

## What might break, which is the actual work

| Risk | Why |
|---|---|
| **Dependency wheels** | litestar, msgspec, aiosqlite, cryptography, argon2-cffi, mcp/FastMCP, pyotp. Native builds are where this bites. |
| **PEP 594 removals** | 3.13 removed the "dead batteries" modules. Unlikely to touch us, must be checked rather than assumed. |
| **PEP 765** (3.14) | `return`/`break`/`continue` in a `finally` block is now a syntax warning. Cheap to grep for. |
| **pyright** | A new interpreter changes what it infers. Expect churn, and treat any new complaint as a real finding rather than noise to silence. |
| **The Docker image** | The published image pins a base. It moves with this, and the four gates must pass **inside the container**, not only on a laptop. |

## Requirements

| ID | Requirement | Status |
|---|---|---|
| **FR-001** | The floor becomes `>=3.14`, in `pyproject.toml` and everywhere else that states a version. | Draft — the charter was amended to match on 2026-08-01 (`main`, `6393e2b`), so this no longer conflicts with it |
| **FR-002** | CI runs the four gates on 3.14. | Draft |
| **FR-003** | The published Docker image runs 3.14, and the gates pass inside it. | Draft |
| **FR-004** | `from __future__ import annotations` is removed where PEP 649 makes it redundant — completely, not partially. A codebase half-migrated is worse than either state, because the next reader cannot tell which convention applies. | Draft |
| **FR-005** | Documentation stating a Python version is updated in the same change, including the README and the self-hosting guide. | Draft |
| **FR-006** | Every dependency resolves and installs on 3.14 with no pinned exception. A single "temporarily pinned for 3.14" is the seed of the next stuck migration. | Draft |

### Non-functional

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| **NFR-001** | No behaviour change. This is a floor move, not a rewrite. | The suite passes unchanged, apart from edits forced by removed stdlib. | Draft |

## Scope discipline

**Adopting the new features is optional and separable.** FR-001 to FR-003 are the migration;
`copy.replace()` and `TypeIs` are opportunistic cleanups that could each be their own change.

The one exception is **FR-004**, which belongs in the migration itself: `from __future__ import
annotations` becoming redundant is a *consequence* of the move, and leaving it half-done means
two conventions in one codebase.

## Open questions

All three are now decided. Nothing here is waiting on anyone.

1. **~~Which version?~~ Decided 2026-08-01: 3.14.** Finished, two patch releases behind it, and
   the version that carries PEP 649 — the only change here with a real payoff. 3.15 was
   rejected for one specific reason rather than a vague one: a `.0` is where dependency wheels
   are missing and native builds fail, and this project depends on cryptography, msgspec and
   argon2-cffi. Revisit at 3.15.2.
2. **~~Free-threaded build?~~ Decided 2026-08-01: explicitly out of scope**, and recorded so it
   is not re-argued each release. See below.
3. **~~Is anything actually pinned to 3.12?~~ Answered 2026-08-01: no.** Checked
   exhaustively during Phase 0 — see the table in `plan.md`. Every occurrence of the version
   is a *declaration* (pyproject, Dockerfile, CI, README, CONTRIBUTING, the charter,
   `.kittify/metadata.yaml`); none is a *constraint*. No code branches on the version and no
   dependency caps it.

## Free-threading: ruled out, and why

The no-GIL build is opt-in from 3.14. It is **out of scope for this hub**, deliberately, and
the reasoning is written here so nobody has to reconstruct it.

**Where it would help, we have nothing.** Free-threading pays for CPU-bound work running in
parallel threads. This hub is I/O-bound throughout: asyncio for everything, with blocking
network calls pushed to threads precisely so they do not occupy the loop. There is no
computation to spread.

**Where we do have concurrency, the design refuses it anyway.** Exactly one process opens the
SQLite file (ADR 0005, ADR 0006). Multiple writer threads are not a capability we want and
then cannot use — they are a thing the storage model rules out on purpose.

**And it is not free.** A second interpreter build to test, a smaller pool of wheels, and more
variance in behaviour, in exchange for parallelism with nothing to parallelise.

Revisit only if this hub ever grows genuinely CPU-bound work. Nothing on the roadmap does.

## Out of scope

| Deferred | Why |
|---|---|
| The free-threaded build | See open question 2 |
| Rewriting anything for its own sake | NFR-001 — this is a floor move |
| 3.15 | Revisit when it has patch releases behind it |
