# Resume Prompt — Restart Test And Release Gate

Written 2026-07-27 22:37 UTC by pablo_fantomas (`codex-gpt-5`) immediately before the
operator restarts this agent to test the wake/restart behavior.

Paste this into the restarted agent, then read it top to bottom before acting.

## First Actions

1. Read `AGENTS.md`.
2. Read `http://hub.example:8080/prompts/agent`.
3. Run `agent-inbox doctor --hub http://hub.example:8081`.
4. Call the agent-inbox MCP `ping`, then check unread mail.
5. Run `git pull --ff-only` and inspect `git status --short --branch`.

At handoff, the operator asked pablo_fantomas to commit and push everything, then restart
this agent. This file supersedes the older
`doc/resume/2026-07-27-handover.md` where it says the release-gate WIP must be left alone.
The release-gate work is now intentionally being finished and committed.

## Expected Repository State

The commit being prepared should include:

- release-gate implementation in `src/agent_mailbox/release_gate.py`;
- tests in `tests/test_release_gate.py`;
- workflow updates in `.github/workflows/release.yaml` and `.github/workflows/docker.yml`;
- `doc/resume/README.md`, defining resume filename rules;
- this resume prompt;
- removal of `agent-mailbox.toml` from git tracking.

`agent-mailbox.toml` should remain locally available but ignored. The fix is intentional:
the file contains deployment-local identity/hub configuration and was tracked only because
ignore rules do not untrack files already in the index.

## Release Gate Shape

The old WIP assumed the prompt install floor equals the release version. That is wrong
after `prompts.MINIMUM_CLIENT = "0.17.1"`.

The intended split is:

- **Prompt floor check:** verify the onboarding prompt advertises
  `agent-inbox[clients]>=MINIMUM_CLIENT` and that uv can resolve that requirement.
- **Release artifact check:** after PyPI publish, verify uv can resolve the exact
  `agent-inbox[clients]==<released_version>` artifact.

Workflow intent:

- `docker.yml` checks only `--check prompt-floor` before pushing a prompt-bearing image.
- `release.yaml` checks `--check release-artifact` after PyPI publish.

The gate must exercise uv's resolver/install surface, not PyPI JSON metadata.

## Wake Restart Test

Wake work is already committed, released as `v0.20.0`, and deployed to examplehub. The important
commits are:

- `6593b75` — `install-hook --rewake` installs a real waiter.
- `6c90bb4` — hub restarts no longer silently end an eight-hour wait.
- `adc8c32` — Codex/OpenCode wake research; hub is harness-agnostic, client wake parity is
  not.

The operator is restarting this agent to observe restart behavior. After restart, check
whether `SessionStart` notices waiting mail and whether a Claude Code TUI idle wake still
works if the operator tests it.

Useful checks:

```bash
jq '.hooks.Stop[0].hooks[0]' .claude/settings.json
agent-inbox --version
agent-inbox doctor --hub http://hub.example:8081
```

Expected project-local Stop hook, if installed:

```json
{
  "type": "command",
  "command": "uv run agent-inbox wake-check --event Stop --wait --poll-interval 5 --wait-timeout 28800",
  "timeout": 28810,
  "async": true,
  "asyncRewake": true
}
```

Undo if it loops or interferes:

```bash
uv run agent-inbox uninstall-hook
rm -f .agent-mailbox-wake.lock
```

Do not remove `.agent-mailbox-seen.json` unless you intentionally want existing unread mail
announced again.

## Validation To Recheck

Before trusting the pushed state, rerun:

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

At the time this handoff was written, focused release-gate tests were already passing after
the `MINIMUM_CLIENT` split was applied. Full gates still need to be rerun after this file is
created and before the commit is pushed.

## Coordination Notes

- Nicole landed the wake work and separately fixed the transient-hub-failure waiter bug.
- Nicole also researched Codex/OpenCode wake capabilities. Carry forward the narrowed
  claim: the hub is harness-agnostic; idle-wake capability is client-specific.
- Ludmila is the host/coordinator. Check and respond to mail before and after substantial
  work.

