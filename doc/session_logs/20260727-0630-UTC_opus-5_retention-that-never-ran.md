# Retention that never ran, and a floor that could not be installed

| Time | Branch | Commits | Task |
|------|--------|---------|------|
| 2026-07-27 00:00–06:30 UTC | main | `6ff7bf7` … `78cf528` (~24) | scheduled-purge-01KYGBQ4; the prompt's install floor; the-api FR-014 |

Agents: nicole_ruzickova (claude, admin), ludmila_coe (host), pablo_fantomas (codex,
silent throughout this stretch). Continues
`20260726-232400-UTC_opus-5_compact-inbox-and-the-wedged-hub.md`.

## What we were asked to do

Plan the outstanding missions, then — after the planning turned up something worse than
the thing being planned — "don't change the doc, just fix expiry", and add a console
control to trigger it.

## The finding that reframed the mission

`Mailbox.expire()` was written, tested, documented as running "on every mailbox open",
and **called by nothing**. Not `serve.py`, not any policy's `on_open`, not a route, not a
CLI command. `House.expire()` existed only to forward to it and had no callers either.

Meanwhile the onboarding prompt told every arriving agent *"Mail expires after about a
fortnight of a conversation being idle."* That had never been true. No message on any
hub had ever been removed by retention.

So the scheduled-purge mission was not an optimisation of retention. It was the caller.

A second thing fell out for free: expiry was accidentally O(n²) — `thread_root` rebuilt
its index on every call and `expired_object_ids` called it twice per message — **4,510 ms
to purge a 10,000-message store against a 250 ms budget**. `thread_roots` resolves every
root in one pass: **4.7 ms**, and linear. That closed `gc-decapitates-threads` NFR-001,
which had also never been checked.

## What shipped

Eight releases, 0.18.0 through 0.18.7, each deployed to examplehub and verified live.

- An asyncio task in the hub, started by Litestar's lifespan, holding the `House`
  directly. No sidecar.
- `/maintenance` in the console: preview every time, button separate.
- `GET /observe/purge` (operator-only, lists subjects) and `GET /observe/purge/status`
  (any authenticated caller, no mail).
- `agent-inbox hub` prints a sentence; `agent-inbox retention` prints the object.
- The prompt's install floor is now `MINIMUM_CLIENT`, not the hub's own version.
- `/schema/openapi.json` — `the-api` FR-014, unbuilt since that mission shipped.

## What we learned

**The strongest lesson is a shape, not an incident.** Three separate defects tonight were
the same shape — *a check that passes because it had nothing to look at*:

- the loop's own death was silent, so "scheduled" in a log proved nothing;
- a field-equivalence check passes vacuously when the client returns no items — which is
  precisely the 0.17.0 bug it would be built to catch;
- a compatibility probe run from the repo root imports the *current* package while
  believing it tests the old one, and every assertion passes.

The fix is identical every time: **establish your premise before asserting on it.** The
regression test that had to be run with its own fix deleted before it could be believed
is the same lesson in miniature.

**I rebuilt the bug I was fixing, inside the fix.** The purge loop slept a full interval
before its first cycle; examplehub was being redeployed every fifteen minutes, so every
restart pushed the first cycle another hour away. Retention configured, reported as
scheduled, and running *never* — the exact failure the mission existed to end. Found only
because ludmila_coe asked for a production log line and there was none to give.

**A gate that fails for the wrong reason is worse than no gate**, because it gets muted
and everyone still believes it is watching. That argument shaped three decisions: field
equivalence rather than byte-identical CLI output, `probe_setup_failed` as a distinct
verdict, and the baseline read before accusing a client of losing mail.

**Pinning the prompt's floor to the release was wrong twice over.** It demanded an
upgrade nobody needed, and because PyPI's install index trails a publish, it guaranteed a
window on *every* release where the hub advertised something unresolvable. ludmila_coe
measured it at about five minutes on 0.18.6. Four incidents across two agents before
anyone stopped calling it bad luck.

**Environment drift cost two red builds** and "remember to unset the variables" was not
a fix — I forgot between saying it and the next push. `tests/conftest.py` now strips
every marker in `ENGINE_MARKERS` for every test, so local and CI cannot diverge.

**A third red build was plain carelessness**: checks and commit on separate lines of one
block, so `&&` protected only the first half and the commit ran on failing checks.

**And I committed another agent's uncommitted work again**, via `git add -A src tests`,
having promised in writing not to. Backed out in `6a733d0`, byte-identical, with the one
exception (`ReleaseGateError`) left in place because removing it would have broken his
working tree. `git add -A` is not safe in a shared worktree and care is not a substitute
for naming files.

## What made the difference

Five of tonight's defects were found by ludmila_coe, not by me: the timestamp tie that
could hide mail for ever, the silent loop death, the starvation, a health check nobody
could reach without delete rights, and a smoke test that proved nothing because the
mailbox was empty. The common thread is that she declined the easier form of evidence
every time I offered it — "it is tested" instead of "here is the production log line",
"the fixture matches" instead of "the fixture was captured".

## Next

- **Pablo has four things**: the release gate (finished, uncommitted, now ten releases
  unguarded), shared-tokens, a view on the floor change, and the compatibility gate.
- **The compatibility gate is designed and unbuilt** — see the compact-inbox spec.
- **The rename is still unfinished** and now has evidence from three directions.
- **The first real purge cannot happen until about 2026-08-07.** Until then every cycle
  logs `removed_threads=0`, which is the evidence the retention-window question needs.
