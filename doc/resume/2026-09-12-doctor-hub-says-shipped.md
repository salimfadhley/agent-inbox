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

## 2026-09-15 — v1.4.2 shipped (#70, closed)

Generated wake hooks (omp extension, opencode plugin) carry the installing machine's interpreter path; the installer now adds an ignore rule anchored to the one file on every write path (`hookconfig.keep_out_of_git`), `doctor` has a `hook safety` line via `ignores.exposed_hooks` with the three states, and outside a repository `doctor` says so instead of claiming safety. `373b190`. Deployed, proved, announced. Not done: `.claude/settings.json` (merged, often shared) — noted on the issue.

## 2026-09-15, later — v1.5.0 shipped (#67); #52 parked

- **v1.5.0 (#67):** multi-id `peek_message` with completeness; new `reply_messages` with per-item outcomes; safe retry by looking for the caller's own identical reply on the thread before sending (`mcp_client._existing_reply` / `_reply_once`); unknown means not sent. Spec `batch-inbox-handling-in-mcp-01M2JHEC`. Deployed, proved, announced. **#67 stays open** for the reporting session's live round trip (SC-1).
- **#52 parked with data:** 40 agents, 11 with `host`, all 11 different strings — nothing to group on exact equality. Enablers proposed on the issue (doctor hint / `profile refresh`); not built.

## 2026-09-17 — v1.6.0 shipped: Codex waking (#71)

Research verified against `openai/codex` `e269f21` and the installed 0.153.4: Claude-shaped hooks in `.codex/hooks.json`, Stop exit-2 = continuation prompt, **trust** (only hooks a human approved in `/hooks` run; hash over event/command/timeout), Stop hooks synchronous. Built as a third renderer (`hookconfig.codex_apply`/`install_codex`), `--rewake` = 10-minute hold with `wake-check --no-rearm`, stdin drained, `doctor` reports presence only. Spec `wake-a-codex-agent-01M2QGEM` (decisions: hook file ignored; no cold wake). Deployed, proved, announced. **#71 open** for the owner's live test; Windows `cmd.exe` quoting of the interpreter path is the known risk.

## 2026-09-21 — v1.6.1: Windows hook quoting (#71)

A Codex agent on Windows reported every generated hook failing with exit 1: `default_command` used `shlex.quote` (single quotes) and Codex on Windows runs hooks through `COMSPEC` = `cmd.exe /C` (verified `command_runner.rs` at `ebc05da`; PowerShell is not the hook shell). Fixed with `hookconfig.quote_for_shell` (bare on Windows for ordinary paths, else double quotes, never single) and `split_command` for omp's argv; the rendered command is launched through `sh -lc` in `tests/test_windows_hook_quoting.py`. `f032848`, deployed, proved, announced. **#71 still open:** the Windows agent must upgrade, reinstall, re-trust in `/hooks` (command text changed) and run Tests A–D. **#72** (AntiGravity/Gemini waking, `.agents/hooks.json`) is filed and untouched — next mission after #71 verifies.

## Also open

- #65: **idle wake live-verified 2026-09-14** by four omp sessions on Windows (coordinator `mirco_abrahamsson`; `gyeongsug_rascon` observed directly). Remaining: the mid-turn `followUp` check, requested from that group by mail; close #65 when it reports. espen_luo's macOS run is welcome, not blocking.
- #64 opencode waking, awaiting `aurelia_saahaa`'s live verification.
