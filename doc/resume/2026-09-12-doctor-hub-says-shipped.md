# 2026-09-12 — v1.3.0 shipped (doctor `hub says`, #68); omp live wake test still pending (#65)

Everything is on `main`, tagged `v1.3.0`, deployed to the stodge node and proved (`verify-deployment`: 5 checks, hub and console both 1.3.0). Local tool at `~/.local/bin/agent-inbox` is 1.3.0. #68 is closed. The open item is unchanged: the **live idle-wake test on omp** with `espen_luo`, who has the steps by mail (restart omp → `ping` says espen_luo → `install-hook` → restart → reply → idle; then I send mail).

## What shipped

- `doctor` prints `hub says` after `hub check`: who the hub serves this caller as (`you.verified` from `remote_doctor`) beside the name the config sends (`you.claimed`). Four cases; a token bound to a different actor is a failure that names both names and exits 1. Older hubs: no line. `whoami` carries `hub_says`. Helper `_hub_says` in `cli.py`; tests in `tests/test_doctor_says_who_the_hub_thinks_you_are.py`.
- `join` now installs waking for the joined harness via `install_for(engine, …)` — omp extension / opencode plugin — instead of the Claude-only `install(...)`. **This is `espen_luo`'s fix**; it was uncommitted in the shared worktree and got swept into my commit `8c5a46f`. Credited on #65 and to them by mail. Lesson saved to memory: `git diff` every shared file before staging.

## Deploying, for next time

Dispatch the private repo's workflow after the tag's Release and Docker runs are green (they are titled simply "Release" / "Docker image"; match by creation time after the tag, not by commit title): `gh workflow run deploy.yml -R salimfadhley/agent-inbox-private -f version=<v>`, `gh run watch`, then `verify-deployment --hub https://api.hub.stodge.org --prompt https://hub.stodge.org/prompts/agent --expect <v>`. Local `flyctl` login has lapsed.

## 2026-09-14 — v1.3.1 shipped

Both follow-ups from the Windows report are done, deployed and proved (hub and console 1.3.1): install floor 1.2.0 with a derived `MODULE_COMMAND_FLOOR` (`3933b36`), and `[agents.ohmypi]` read as `omp` through `client.entry_key` on every read and write, never duplicated or migrated (`7971c3f`). Announced; #65 updated. **Deploy gotcha:** the Release run to wait for is *any* successful "Release" run created after the tag — a `main` push a few seconds later produces a second, *skipped* Release run, and a poller that takes the newest one waits for ever.

## 2026-09-14, later — v1.4.0 and v1.4.1 shipped

- **v1.4.0 (#69, closed):** the console graph takes `?days=N` (number input, Apply, All time); the cutoff reaches the hub's `survey` as `since`; node sizes summed from the windowed edges, not lifetime `busiest`; empty window and bad input handled; the dead July date literal behind "recent" replaced by the window. `bc74fa1`.
- **v1.4.1 (#66, closed):** the prompt says reply-not-send when answering, shows `reply`, Manners names the verb; MCP instructions mark the pair, `send_message`'s description redirects. `1bf798d`. Both deployed and proved; announced together.
- **Site:** the GitHub Pages front page now names opencode and Oh My Pi, replaces the stale "cannot be interrupted" note with the waking story, and has a "Woken on three harnesses" section (`gh-pages` `d08256e`).
- **Deploy:** waiting on PyPI + Docker Hub JSON directly (not run names) worked cleanly for both releases — keep that shape.

## Also open

- #65: **idle wake live-verified 2026-09-14** by four omp sessions on Windows (coordinator `mirco_abrahamsson`; `gyeongsug_rascon` observed directly). Remaining: the mid-turn `followUp` check, requested from that group by mail; close #65 when it reports. espen_luo's macOS run is welcome, not blocking.
- #64 opencode waking, awaiting `aurelia_saahaa`'s live verification.
