# agent-mailbox-old — historical reference

This is the **superseded implementation** (`agent-inbox`, up to v0.10.2). It is kept
so the reasoning and the code behind it can be read later. It is:

- **not installed** — not in `[tool.hatch.build.targets.wheel].packages`
- **not built, linted, type-checked or tested** — excluded from all four gates
- **never executed again**

It is deleted once the new system is green.

## What is worth reading here

- `src/agent_mailbox_old/mailbox.py` — the whole core: routing, delivery, threads,
  expiry, renames. Note `read_thread` (per-turn visibility, mission 0020) and
  `_purge_expired` (expiry by thread activity, mission 0016).
- `tests/test_integration.py` — **the most valuable file in this directory.** Its
  regression tests encode production failures already paid for. Per the charter, they
  are requirements the new model must also satisfy, not archive:
  - GC decapitating live threads (0016)
  - thread disclosure — party to one turn granted every turn (0020)
  - `role` dropped by `list_threads`, over-required by `whois` (0022)
  - renames with forwarding, and self-exclusion on fan-out (0012)

## Why it was replaced

Not because it was broken — it worked, and ran a live hub. The model underneath it was
the wrong shape. See `docs/decisions/`:

- ADR 0003 — identity was a natural key; six missions were the cost of that
- ADR 0004 — the messaging model now follows ActivityStreams
- ADR 0005 — one API; every client is a client
- ADR 0006 — SQLite stays, with typed columns plus a document column
