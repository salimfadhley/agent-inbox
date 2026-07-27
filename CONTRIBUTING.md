# Contributing to agent-inbox

Thanks for helping. `agent-inbox` is small, generic infrastructure — contributions
should keep it that way.

## Setup

```bash
uv sync --dev
uv run pre-commit install    # optional but recommended
```

You need **Python 3.12+** and nothing else — storage is a single local SQLite file, so
the test suite requires no external services.

## Quality gates

These must pass before a change is complete (CI enforces them):

```bash
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run pyright
```

The whole suite (including the mailbox round-trip tests) runs against SQLite with no
services to stand up.

The exception is `tests/live/`, which skips unless you point it at a running deployment:

```bash
LIVE_HUB_URL=http://<your-hub>:8081 LIVE_CONSOLE_URL=http://<your-console>:8080 \
  uv run pytest tests/live -rs
```

**Read the skip count.** A skipped live test is not a passing one, and `-rs` is what
makes that visible. These tests currently assume a hub with authentication *off*; against
an enforcing hub several fail with 401s that mean nothing.

## Coding standards

Follow [`doc/coding-standards.md`](doc/coding-standards.md) and the project rules in
[`AGENTS.md`](AGENTS.md). In short: full type annotations, absolute imports, specific
exceptions from `agent_mailbox.exceptions` (base `MailboxError`), logging over `print`,
and ruff-clean + pyright-clean.

The package is `agent_mailbox` even though the project is `agent-inbox` — import from
the former, write the latter in prose. `AGENTS.md` explains why.

Keep it **generic** — no deployment-specific hostnames, IPs, secrets, or org names in
code, docs, or tests.

## Commits & PRs

- Small, focused commits with imperative messages (`feat:`, `fix:`, `docs:`, `test:`).
- A PR should keep the gates green and update docs when behaviour changes.

## Releases

Versions come from git tags via `hatch-vcs`.

- **Docker image** — `:edge` on every push to `main`; `:X.Y.Z`, `:X.Y` and `:latest`
  only on a `v*` tag. A merge to main gives you something to try, not something to ship.
- **PyPI** publish happens on a `v*` tag via Trusted Publishing:

  ```bash
  git tag v0.1.0 && git push origin v0.1.0
  ```

Both are **gated on CI passing**, and both then run the release gate in
`agent_mailbox.release_gate`, which asks the two questions a release can fail
independently:

- `--check prompt-floor`, before a prompt-bearing image is pushed: can PyPI satisfy the
  install floor the onboarding prompt advertises (`prompts.MINIMUM_CLIENT`)? That floor
  is deliberately *older* than the release — the index cannot serve a just-published
  version for several minutes, so advertising the current one would hand every new agent
  an install command that fails.
- `--check release-artifact`, after PyPI publish: can a clean resolver install the exact
  version just published? Retried for about five minutes to absorb index propagation.

Both drive real `uv tool install` runs rather than reading PyPI's JSON metadata, so the
gate fails for the same reason an agent would. `--skip-install` exists for local use and
must never be used in a release workflow.

To raise the floor, change `prompts.MINIMUM_CLIENT` to the oldest client that actually
works — the contract for doing so is in a comment above it.

## License

By contributing you agree your contributions are licensed under
[GPL-3.0-or-later](LICENSE).
