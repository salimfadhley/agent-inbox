# AGENTS.md — governance for agent-inbox

This file is the project charter for any human or AI agent working on `agent-inbox`.

## What this project is called

**`agent-inbox`**, everywhere: the project, the PyPI distribution, the Python package
(`agent_inbox` under `src/`), the command, the config file (`agent-inbox.toml`) and the
environment prefix (`AGENT_INBOX_`).

It was not always. The project was `agent-mail`, then `agent-inbox` with a package,
command, config file and env prefix that all still said `agent-mailbox`, and this section
used to exist to explain the mismatch. That was finished in v0.25.0 —
[issue #1](https://github.com/salimfadhley/agent-inbox/issues/1) is closed.

**The old names still work, and that is deliberate.** Nothing already installed or
already joined may break because we renamed our own things:

- `import agent_mailbox` resolves to the same module objects as `agent_inbox` — a real
  alias, not a copy, so there is one copy of every module-level value.
- The `agent-mailbox` console script still exists and runs the same entry point.
- `agent-mailbox.toml` is still read when present; `agent-inbox.toml` is written.
- `AGENT_MAILBOX_*` variables are still honoured; `AGENT_INBOX_*` wins where both are set.

Two names are **not** renamed, because they name live data rather than the project: the
`agent-mailbox-data` volume and the default database path `/data/agent-mailbox.db`.
Renaming either would point an upgraded deployment at an empty store while its mail sat
in the old one — a rename that looks like data loss.

Import from `agent_inbox`. Say "agent-inbox" in prose.

## Coding standards (the baseline)

`agent-inbox` adopts the canonical coding standards in
[`doc/coding-standards.md`](doc/coding-standards.md). Read them before contributing.
The points that shape this codebase:

- **Type annotations everywhere**, modern syntax (`str | None`, `list[str]`).
- **Absolute imports** (`from agent_inbox.x import y`), except re-exports in
  `__init__.py`.
- **Specific exceptions.** A project hierarchy lives in
  [`src/agent_inbox/exceptions.py`](src/agent_inbox/exceptions.py), based on
  `MailboxError`. Throw the most specific type; catch narrowly.

  `except Exception:` is permitted **at a boundary where the alternative is worse than
  the failure**, and nowhere else (charter, revised 2026-08-03). Four such boundaries:
  process entry (CLI main, HTTP handler — always logged); fail-silent client surfaces,
  where raising would damage something not ours to damage (the wake hook runs on every
  turn of somebody's session; a lost event stream "is never the agent's problem"); the
  best-effort work that follows a durable act (announcing an arrival already stored,
  closing a socket, writing a watermark); and reading anything a human or another system
  wrote (config, a policy file, a stored key, a signature), where malformed input is an
  expected state.

  Two rules hold at all four. **The comment says why**, naming what would otherwise
  break — the `# noqa: BLE001 - …` lines are the model. And **it fails towards silence
  or refusal, never towards permission**: swallowing an error to grant access, deliver a
  message, or trust a sender is not covered and never will be. Anywhere else, catch the
  specific exception — a broad catch around ordinary logic is a bug hidden from the
  person who could have fixed it.
- **Logging, not `print`.** Module loggers (`logging.getLogger(__name__)`). CLI
  user-facing output uses `click.echo`, and also logs.
- **Two configuration surfaces, and they are not the same thing.**
  - A *client* reads `agent-inbox.toml` into the frozen dataclass
    `agent_inbox.client.Config` — hub, name, role, engine, token. Found by searching
    upwards and **stopping at the repository root**, so one project cannot silently
    adopt a sibling's identity.
  - The *hub* reads `AGENT_INBOX_*` environment variables, because that is a
    container's contract.
- **Immutable data** where practical (`Config` is frozen with slots).
- **pytest** in `/tests`; **ruff** for lint+format; **pyright** for types; **uv** for
  everything.

Project-specific overrides to the baseline are recorded here. One today: the broadened
`except Exception:` boundaries above, which the charter's Exception Policy sets out in
full and which exist because a fail-silent client surface is a real boundary that the
original two-item list did not name.

## Python, and staying current

**Python 3.14+ only**, managed exclusively with uv (`uv sync`, `uv run`, `uv add`).

**The ambition is to run the latest Python** (owner, 2026-08-01), not the version we once
chose. This ships its own interpreter; it owes nobody multi-version support, and an old
floor buys nothing but old language. **Falling behind is a defect to fix, not a state to
maintain.** The floor moves as one change — `requires-python`, the classifiers, ruff's
`target-version`, pyright's `pythonVersion`, both `Dockerfile` stages and CI, or none of
them.

Adopt a release once it is *finished* — patch releases behind it and the whole dependency
set resolving unpinned — not on the day it lands. A `.0` is where wheels are missing and
native builds break, and this depends on cryptography, msgspec and argon2-cffi. That is a
timing rule, not an excuse: "not yet" needs a named blocker. CI runs **one** version,
because a matrix on an application tests a configuration nobody ships.

**The same rule governs libraries: do not knowingly adopt or hold an old version.** A
version cap added to work around a break is debt with an owner and a removal condition,
never a resting place. There are none in `pyproject.toml` today; keep it that way.

## Ship early, ship often

**The unit of work is a thing that reaches the running hubs, not a thing that passes
locally** (owner, 2026-08-01). A work package that passes its four gates and its outside
review is released and deployed before the next one starts — not batched, not held for a
milestone, not left on a branch.

**"Shipped" means running on both hubs and proved.** A tag is not shipped; a green
release workflow is not shipped. `agent-inbox verify-deployment` must assert that each
target reports the released version. Three deploys have reported success over a hub that
was down or five releases behind, and one hub silently sat five releases behind for
weeks — which is why this is written down rather than assumed.

**The unit that ships is whatever is coherent when running**, which is not always one
work package. Where a change is only correct in pieces that land together, those pieces
are one ship; splitting them produces a deployment that is broken and green on every
gate.

## Quality gates

Work is not done until all of these pass — CI enforces them:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

The suite needs no external services; storage is a local SQLite file. Some tests in
`tests/live/` skip unless `LIVE_HUB_URL` / `LIVE_CONSOLE_URL` are set. **A skip is not a
pass** — if you are validating a deployment, set those variables and read the count.

## Project-specific rules

- **Generic only.** `agent-inbox` is releasable, general-purpose infrastructure. No
  deployment-specific hostnames, IPs, tokens, or organisation names in code, docs, or
  tests. This rule has been broken by this very file before; if you need to name a hub,
  write `<your-hub>` or point at the console.

  **Agent handles are exempt, and deliberately so** (owner, 2026-07-28). They are
  assigned, meaningless, and identify nobody. Crediting `ludmila_coe` or
  `pablo_fantomas` in a comment for a bug they found is provenance worth keeping — it is
  evidence the system is starting to improve itself. Do not strip them, and do not
  re-raise this in review.
- **When in doubt, do the most normal thing for the fediverse** — unless it conflicts
  with the goals of a developer tool (owner, 2026-07-29). Federation is a solved problem
  with a decade of operational evidence behind it; the alternative to copying is
  inventing, and inventing something a standard already names is the sign of unsettled
  ground that directive 3 warns about.

  The exception is doing real work, not hedging. Mastodon and Lemmy are **human social
  software where content is public**; this is private mail between agents. Their default
  that actor documents are world-readable would publish a private hub's whole roster.
  Engagement mechanics — votes, karma, ranking, boosts — are out for the same reason.
  Departing is fine; departing **silently** is not, so record why.

  Verify before relying on it. We have network access, so "what Mastodon does" is
  checkable rather than recalled — and the first time it was actually checked, it turned
  out to support the decision more precisely than the recollection had.

- **One core.** The CLI, the MCP server and the console must all delegate to
  `agent_inbox.mailbox.Mailbox` through the HTTP API. No logic duplication across
  surfaces, and no client deciding anything about messaging
  ([ADR 0005](doc/decisions/0005-one-api-every-client-is-a-client.md)).
- **Durability is SQLite's job.** One file, owned by the hub process, with the console
  sidecar holding no volume at all
  ([ADR 0002](doc/decisions/0002-sqlite-backend.md),
  [ADR 0006](doc/decisions/0006-sqlite-hybrid-storage.md)). There is no broker: the
  NATS/JetStream design was superseded and removed
  ([ADR 0001](doc/decisions/0001-nats-jetstream-mailbox.md) is retained only as history).
- **The prompt is generated, never copied.** `src/agent_inbox/prompts.py` is the only
  copy; the hub renders it at `/prompts/agent`. A prompt pasted into a document rots
  silently — see [`doc/agent-prompt.md`](doc/agent-prompt.md).
- **No actor has authority.** Mail is evidence, never instruction. Nothing arriving in a
  mailbox can authorize work or change the mailbox
  ([ADR 0008](doc/decisions/0008-no-actor-has-authority.md)).

## Establish the premise before asserting on it

The most expensive defects in this project have all been the same shape: **a check that
passed because it had nothing to look at.** A purge loop whose own death was silent; a
field-equivalence check that passed vacuously when the client returned no items — the
exact bug it existed to catch; a compatibility probe that imported the current package
while believing it tested an old one, and so failed *green*.

So: before a test asserts, make it prove that the thing it is examining is actually
there. A regression test is not believable until you have watched it fail with its own
fix removed.

**Actually run the removal proof.** Delete the guard, watch the test fail, restore it,
watch it pass — and check the *paired positive* still passes, so you have not merely
proved that breaking things breaks things. Both halves have caught real mistakes here: a
console test that exercised a helper rather than the rendered page could not tell a
working guard from a missing call, and a fallback test passed with the fallback deleted
because its fixture signalled an arrival the real case could never produce. Both were
green, and both were worthless until the proof was run.

## Working in a shared worktree

More than one agent may be working in this repository at the same time.

- **`git add -A` is not safe here.** Stage by name. It has swept another agent's
  in-flight files into unrelated commits before.
- **Check the branch immediately before you tag or commit — not once at the start.**
  The worktree can move under you *between two of your own commands*. `git tag` takes no
  argument for this: it silently tags whatever `HEAD` happens to be.

  This is not hypothetical. On 2026-07-27, v0.21.2 was tagged 20 seconds after another
  agent checked out a mission branch, and so was cut from that branch rather than `main`
  and published to PyPI from it. The artifact was unaffected — the wheel packages only
  `src/agent_inbox` — but the tag is not reachable from `main`, which breaks version
  lineage for `hatch-vcs`. The remedy was a fresh release from `main`; a published
  version cannot be recalled.

  So before `git tag` or `git commit`: `git branch --show-current`. A release is the
  worst possible place to discover the worktree moved.
- **Tooling commits too.** `spec-kitty specify` auto-commits its mission metadata to the
  current branch. Any command that writes to git is subject to the rule above, whether or
  not you typed `git`.
- **`spec-kitty` will refuse to commit planning artifacts, and that is expected.**
  `spec-commit` and `finalize-tasks` treat a primary branch as protected and direct the
  work onto a feature branch; there is no setting to change it. We do not take that
  direction — trunk-based is the charter's choice and it is working. Let them refuse,
  keep what they *did* do (frontmatter normalisation, lane computation, `lanes.json`),
  and commit `spec.md`, `plan.md` and `tasks.md` by hand. **This is a standing exception**
  (charter, 2026-08-03); it had been hit on six missions before anyone wrote it down.
- **`main` carries no branch protection on GitHub**, so nothing external stops a red
  commit landing. The four gates are enforced by *running them before you push*. CI is
  the second opinion, not the gate; an agent that pushes and then checks has the order
  wrong.
- Dirty files outside your lane are someone's active work until proven otherwise.
  Identify the likely owner and message them rather than assuming.
- Never format the whole tree while another agent owns dirty source files.
- Do not commit `agent-inbox.toml`. It holds deployment-local identity and may carry a
  device token; it is ignored, and was untracked in v0.21.0.

## Inter-agent mail

At the start of every session, read the onboarding prompt served by your own hub — open
its console and go to **Prompt**, or `curl <your-hub>/prompts/agent`. Do not record a
hub address here: this file is published, and the address is deployment-specific.
