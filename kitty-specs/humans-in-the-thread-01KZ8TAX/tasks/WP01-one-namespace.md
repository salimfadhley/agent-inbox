---
work_package_id: WP01
title: One namespace
dependencies: []
requirement_refs:
- FR-001
- FR-002
- FR-013
tracker_refs: []
planning_base_branch: main
merge_target_branch: main
branch_strategy: Planning artifacts for this mission were generated on main. During /spec-kitty.implement this WP may branch from a dependency-specific base, but completed changes must merge back into main unless the human explicitly redirects the landing branch.
subtasks:
- T001
- T002
- T003
- T004
- T005
agent: python-pedro
history:
- at: '2026-08-05T13:00:00Z'
  actor: system
  action: Prompt generated via /spec-kitty.tasks
agent_profile: python-pedro
authoritative_surface: src/agent_inbox/merge.py
create_intent:
- src/agent_inbox/merge.py
- tests/test_namespace_merge.py
execution_mode: code_change
owned_files:
- src/agent_inbox/merge.py
- src/agent_inbox/auth/service.py
- src/agent_inbox/auth/store.py
- src/agent_inbox/auth/records.py
- tests/test_namespace_merge.py
- tests/test_operators.py
role: implementer
tags: []
---

# WP01 — One namespace

## ⚡ Do This First: Load Agent Profile

Load the assigned profile (`python-pedro`) via `/ad-hoc-profile-load` before reading
anything else.

## Objective

An operator account and a mailbox identity become **the same thing**. Signing in as
`admin` gives you the `admin` mailbox; that access is what the admin role now means.

This is the mission's premise. Everything after it needs a human who can be attributed.

**It is also the only package here that can hurt an existing deployment**, because it
changes a login. It ships alone, first, and the migration is loud.

## What is already there

Read before writing. Verified in the source on 2026-08-05.

- **Auth and mail share one SQLite file** (`config.db`). `SqliteStore` and
  `SqliteAuthStore` are opened on it separately, but it is one file — so the merge is
  **one transaction**, not a two-store dance with a window in the middle. This was not
  obvious and it simplifies the package considerably.
- `auth_users` is keyed on `username TEXT PRIMARY KEY`.
- `naming.validate_operator_name` **already exists** and is already called from
  `AuthService.add_operator` (shipped 0.60.0). New registrations are handled. **Do not
  rebuild it.** What is missing is everything about accounts that already exist.
- `RESERVED_NAMES` is now the union of `ADDRESSING_KEYWORDS` and `STANDING_RESIDENTS`.
  `admin` and `host` are standing residents.
- `AuthService.bootstrap()` seeds `admin` and re-issues its password every boot until
  somebody enrols.

## The decision you are implementing

**Operators adopt the agent naming rule** (owner, 2026-08-05). A username must be a
valid actor name.

Two different answers to that one rule, and the difference is whether a human is
standing there:

- **Registration refuses** — done, in 0.60.0. Somebody typing into a form is told the
  rule and the spelling that would work.
- **Migration renames** — this package. An existing `sal.fadhley` becomes `sal_fadhley`
  at upgrade, and that is the login from then on.

The migration option was chosen over refusing to start (an upgrade that takes the hub
down over a punctuation mark) and over leaving them mailboxless until they rename (two
classes of human, indefinitely, with an invisible incentive to fix it).

**The cost of the chosen option is that somebody's login changes and they find out when
it stops working.** T002 and T003 exist to pay that cost down; do not treat them as
polish.

## Subtasks

### T001 — The link between an operator account and an actor

One identity, so signing in as a human gives access to that human's mailbox.

Decide and record *where the link lives* — whether an operator row gains an actor, or
an actor gains a flag, or the two are the same row. Whatever you choose, the property to
protect is that **there is exactly one place that answers "is this name taken"**. Two
uniqueness checks that nearly agree is how a human and an agent end up sharing an inbox.

### T002 — Migrate existing operators, renaming where the name is not usable

`sal.fadhley` → `sal_fadhley`, and that is the login from then on.

Three things the chosen option's cost implies, all of them required:

- **Log it loudly.** A login changed silently is the failure mode; the log is the only
  place some operators will ever see it.
- **Report both names** — old and new — from the upgrade, together, so somebody reading
  the output can act on it without reconstructing what happened.
- Case needs no migration: usernames were already stored folded. Do not write a rename
  for it and do not claim one in the report.

### T003 — Refuse to migrate a collision rather than merge two people

`sal.fadhley` and `sal_fadhley` both existing is not a case to resolve cleverly. Both
normalise to the same name, and merging them **joins two people's mail**.

That account is **not migrated**; the refusal names both usernames and says what a human
must do. The rest of the migration proceeds — one bad account does not block a hub.

Assert the negative: after a collision, both accounts still exist, separately, with their
own mail.

### T004 — `admin` is one identity, and its existing mail survives

FR-013. The standing `admin` drop box exists so anyone can *"raise a concern about how
this mailbox operates"*, and there is mail in it on running hubs.

The reservation stays; what changes is that `admin` now names one identity rather than
two things that never met. **Mail already sent there remains reachable** by whoever holds
the account.

`host` is the case the spec did not settle, and the plan settled it: it is reserved on
the same line as `admin` but is **not** an operator account — it is a role an agent
performs. Leave it an agent-held standing resident. If you find a reason that is wrong,
say so rather than deciding it here.

### T005 — Prove it against a store populated *before* the change

NFR-003, and the reason it is its own subtask: **a migration test that builds its store
with the new code proves nothing.** It exercises the post-migration shape and calls it a
pass.

So: populate a store the old way — agents with names, operators with usernames including
at least one that is not a valid actor name and at least one collision — *then* migrate,
*then* assert. No existing agent loses its name or its mail.

Run the removal proof. Delete the migration and watch this fail; restore it and watch the
paired positive (an already-valid operator, untouched) still pass.

## Branch strategy

Planning happened on `main` and completed work merges back into `main`. Execution
worktrees are allocated per computed lane from `lanes.json`.

## Definition of done

- The four quality gates pass: `uv run pytest`, `uv run ruff check .`,
  `uv run ruff format --check .`, `uv run pyright`.
- A store populated before the change migrates with no agent losing name or mail.
- A collision refuses that account and migrates the rest.
- The removal proof has been **run**, both halves, not merely described.
- `admin`'s existing mail is reachable after the merge.

## Risks

| Risk | Why it matters |
|---|---|
| A collision merged rather than refused | Two people's mail in one inbox; not recoverable by reading the code afterwards |
| A silent rename | The operator discovers it when they cannot sign in, with no log to explain it |
| Testing against a freshly built store | NFR-003 passes vacuously — the exact failure this project keeps meeting |

## Reviewer guidance

Ask first: **was the migration test's store built by the old code?** If it was built by
the new code, the package is unproven regardless of how many assertions it has.

Then: what happens to `host`? The answer should be "nothing, deliberately", with a
reason.
