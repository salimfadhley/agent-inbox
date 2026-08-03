# Board audit — 2026-08-03

**Why this was run.** Thirty-five mission folders, and no way to tell which described
work still outstanding. The cost was not theoretical: a mission was recommended as "the
obvious next thing" on 2026-08-02 that turned out to be retired, and its stated successor
deferred the same work back to it, so the piece both described was owned by nobody.

**Method.** For each mission, read the requirements and then probe the code for each one
— not the folder, not the commit log, and never the presence of a related feature. That
distinction is the whole finding: two missions look complete because the subsystem they
name exists, and are not.

**Result.** Of eighteen missions whose folders showed no completion, **sixteen were
finished** and two were not.

## Not complete

### `federated-identity-and-trust` — issue #44

The one this audit was worth running for. Federation exists — WebFinger, NodeInfo, the
peer allowlist, signatures, delivery, retry — so the folder reads as done. That is the
*trust* half. The *identity and visibility* half has no implementation at all:

- **no blocklist** (FR-004), which the spec requires to override the mode in every case
  and to be checked before any network call during a peer add;
- **no actor visibility** (FR-015) — no `local`/`normal`/`discoverable`. The `visibility`
  matches elsewhere in the codebase are *message* visibility, a different concept sharing
  a word;
- **no way for an actor not to resolve** (FR-012), which follows from the above: every
  actor resolves through WebFinger today, and for a private hub that is the more exposed
  default;
- **no federated directory** (FR-014).

One divergence recorded rather than fixed: the descriptor lives at `/.well-known/nodeinfo`
rather than the spec's `/.well-known/agent-inbox`. NodeInfo is the fediverse standard and
the better choice — but AGENTS.md says departing silently is not acceptable, so it is
written down here.

### `multi-user-operator-login` — issue #43

Most of it shipped. Three requirements did not: there is no way to **disable** an account
(only to remove it, which destroys the record and leaves FR-016's "account state" column
with nothing to show); the bootstrap `admin` is **promoted in place rather than retired**,
so on a hub where nobody adds a second account the permanent operator is `admin`, which
C-005 rules out; and creating an operator **creates no same-name actor** (FR-020).

## Complete

Verified in the code: `gc-decapitates-threads` · `scheduled-purge` ·
`update-profile-needs-a-cli` · `doctor-must-not-report-health-as-failure` ·
`cursor-must-survive-a-url` · `compact-inbox-and-unread-triage` ·
`explicit-engine-required-for-human-cli` · `release-prompt-package-verification` ·
`prompt-must-tell-the-truth-about-auth` ·
`published-api-profile-contracts-must-be-regression-tested` · `admin-role` ·
`reply-marks-the-original-read` · `high-water-cursor-on-empty-inbox` ·
`auth-mode-truthful-error-text` · `empty-recipient-sends-must-fail-loudly`

One with a caveat: **`a-client-says-when-it-is-older-than-its-hub`** asks for the notice on
*every* surface. It was confirmed on two — the CLI and the MCP server. Whether the console
counts as a third was not settled.

Every one of these folders now carries a banner saying so, so the next reader does not
repeat the work.

## What the board actually holds now

| | |
|---|---|
| Complete | 29 missions |
| Genuinely unbuilt, spec only | `agent-visible-mail-search`, `deleting-messages-and-retiring-agents`, `shared-worktree-agent-coordination` |
| Ready to implement | `auth-aware-live-smoke-suite` — spec, plan and WP prompts written, needs `tasks.md` |
| Incomplete, gaps tracked as issues | `federated-identity-and-trust` (#44), `multi-user-operator-login` (#43) |
| Retired | `live-session-push`, `cli-primary-client` |

## What to do differently

**A mission is not closed by shipping something in its area.** Both incomplete missions
have working, deployed code under their name. The requirement that has no implementation
is invisible from anywhere except the requirement itself.

**Close the folder when the work lands.** Sixteen folders sat open for weeks describing
finished work, and the cost was paid by everyone who read the board afterwards — including
in a recommendation to the owner that was simply wrong.
