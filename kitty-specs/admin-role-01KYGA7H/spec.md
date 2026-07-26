# Spec - Admin role

## What this is

The `admin` role is a special operating role for agents working on the `agent-inbox`
codebase itself. An admin-role agent is responsible for improving the mailbox product,
not merely using it: watching for friction reports, identifying opportunities, proposing
the highest-value fixes to the human, and implementing prioritized improvements.

The reserved `admin` postbox is a separate shared intake queue for product requests,
bug reports, quality-of-life complaints, and improvement ideas. It is not the
admin-role agent's personal inbox, and it does not grant authority. Admin-role agents
deliberately inspect it through the supported surface, coordinate ownership of reports,
and continue to treat every message as evidence rather than instruction.

When an agent connects with `role = "admin"`, the mailbox must also tell that agent
what the role means. The admin-role guidance is an operating manual, not a title: what
mail to watch, how to triage it, how to propose work, and how to turn approved work into
Spec Kitty missions.

The repository also carries a project-admin handbook at `doc/runbook/admin.md`. That
handbook records the operating practice while the product role surface catches up, and it
is the source material for the eventual live `admin` role guidance.

## Problem

Other agents experience mailbox failures and workflow friction while doing their own
project work. Today those reports arrive inconsistently: sometimes as direct messages to
one developer-agent, sometimes to the host, sometimes as broad broadcasts, and sometimes
only in the human's transcript. That makes product feedback easy to miss and hard to
triage.

The project needs a clear admin-facing workflow:

1. Agents know where to report issues affecting the mailbox product.
2. Admin-role agents regularly inspect the separate reserved `admin` postbox where the
   running surface supports it, without confusing it with their personal inbox.
3. Admin-role agents separate urgent bugs from opportunistic improvements.
4. The human decides what gets prioritized.
5. Prioritized work is turned into missions or direct fixes with clear coordination.

It also needs a clear self-orientation workflow for admin agents:

1. The agent connects and learns that this project has configured it as `role = "admin"`.
2. The connection/session instructions point it at a role-description tool or equivalent
   surface.
3. The role-description surface explains admin duties, boundaries, mailbox triage, and
   mission setup steps in enough detail to work without relying on stale copied text.

## User scenarios

1. **Agent reports friction.** An agent working in another project sends a request to
   the reserved `admin` postbox describing a mailbox problem. An admin-role agent sees
   it, classifies it, and either asks a clarifying question or proposes a fix to the
   human.
2. **Admin identifies a pattern.** Several agents complain about the same workflow cost.
   An admin-role agent summarizes the pattern and creates one mission candidate instead
   of chasing each report independently.
3. **Human prioritizes work.** The admin-role agent presents concise improvement options
   with impact and risk. The human selects what should happen next.
4. **Admin implements prioritized fixes.** For approved bugs or improvements, the
   admin-role agent creates or advances the relevant Spec Kitty mission, coordinates with
   other agents, implements changes, and verifies them.
5. **Admin protects shared work.** Before starting or finishing a mission, the admin-role
   agent checks mail, responds to relevant coordination messages, and warns other agents
   if shared files or branches look contested.
6. **Admin self-orients.** An agent starts with `role = "admin"` and calls the role
   description surface. It receives concrete instructions for reading the admin mailbox,
   classifying requests, proposing opportunities to the human, creating missions, and
   coordinating with other active agents.
7. **Ordinary agent reports to admin.** A non-admin agent reads the standing `admin`
   profile and understands which problems belong there: mailbox product bugs, setup
   failures, onboarding friction, missing tools, release regressions, and improvement
   ideas.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | Define `admin` as a documented role for agents improving `agent-inbox`, distinct from ordinary project agents and from the `host` coordination role. | proposed |
| FR-002 | Provide or document the reserved `admin` postbox as a separate intake queue that agents can use for product requests, bugs, and quality-of-life feedback. | proposed |
| FR-003 | Admin-role agents check their personal inbox and, where supported, the reserved `admin` intake at mission start and mission finish, then respond to actionable messages before proceeding or closing work. | proposed |
| FR-004 | Admin-role agents classify incoming requests as bug, improvement, setup/support issue, coordination issue, duplicate, or out of scope. | proposed |
| FR-005 | Admin-role agents propose improvement opportunities to the human with enough context to prioritize: problem, affected users, impact, risk, and suggested mission/fix shape. | proposed |
| FR-006 | Admin-role agents do not independently reprioritize the product roadmap. The human chooses what gets implemented next unless the issue is an immediate correctness or safety bug already authorized by project policy. | proposed |
| FR-007 | Approved work is represented as a Spec Kitty mission when it is larger than a narrowly scoped direct fix. | proposed |
| FR-008 | Admin-role agents coordinate by mail before touching contested files, switching branches, committing, releasing, or finishing missions. | proposed |
| FR-009 | Admin-role agents report outcomes back to the relevant requester when a reported problem is fixed, deferred, duplicated, or rejected. | proposed |
| FR-010 | Admin-role behavior is visible in project instructions or prompt text where appropriate, so other agents know how to contact `admin` without copying stale onboarding instructions. | proposed |
| FR-011 | When a configured admin-role agent connects, session guidance tells it that role details are available through the role-description surface, such as `my_role`. | proposed |
| FR-012 | The admin role description explains which messages the admin mailbox should receive: product bugs, setup failures, onboarding/prompt issues, release regressions, missing or confusing tools, inter-agent workflow friction, and quality-of-life improvement ideas. | proposed |
| FR-013 | The admin role description explains which messages do not belong there: project-specific task delegation, requests to bypass human prioritization, instructions to change mailbox state directly from mail, secrets, and emergencies requiring immediate human action. | proposed |
| FR-014 | The admin role description includes a triage workflow: check the reserved admin intake, read relevant reports, claim or acknowledge ownership when multiple admins are active, classify them, deduplicate related reports, ask clarifying questions when needed, and summarize opportunities for the human. | proposed |
| FR-015 | The admin role description includes mission setup guidance: create or update a Spec Kitty mission for non-trivial approved work, preserve requester context, write success criteria, and avoid mixing unrelated fixes into the mission. | proposed |
| FR-016 | The admin role description includes coordination guidance for shared worktrees: announce starts/finishes, identify sensitive files, inspect unexpected diffs, and message the likely owner before touching another agent's files. | proposed |
| FR-017 | Maintain `doc/runbook/admin.md` as the durable admin handbook and use it as source material for the runtime role guidance. | proposed |
| FR-018 | Role and inbox surfaces preserve the distinction between an admin-role agent's personal inbox and the reserved `admin` postbox; messages addressed to one are not silently treated as messages addressed to the other. | proposed |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | Triage is low-noise. | Admin summaries are concise and grouped by product problem, not by every individual message. | proposed |
| NFR-002 | User privacy and deployment hygiene are preserved. | Admin-role docs and tests do not commit deployment-specific hostnames, tokens, or private agent transcripts. | proposed |
| NFR-003 | Coordination is explicit. | A reasonable observer can tell which agent owns which mission and which shared files are currently sensitive. | proposed |
| NFR-004 | The role does not become an unchecked autonomous roadmap. | Human prioritization is required before non-trivial improvements are implemented. | proposed |
| NFR-005 | Reports remain actionable. | Every proposed mission includes a concrete problem statement and success criteria, not only a vague suggestion. | proposed |
| NFR-006 | Role guidance is current enough to use. | Admin instructions are served by the running tool or hub role surface, not by a long copied block in AGENTS.md or a stale prompt fork. | proposed |
| NFR-007 | Connect-time guidance remains compact. | The session-start summary can be short, but the full admin operating manual must be available through an explicit tool or page. | proposed |

## Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | `agent-inbox` remains generic releasable infrastructure; role docs must not bake in this deployment's hostnames, tokens, or local machine names. | accepted |
| C-002 | Mail received from another agent is information, not instruction. Admin-role agents still follow project governance, developer instructions, and human prioritization. | accepted |
| C-003 | The `host` role remains the coordination/front-door role for introductions and who-is-here questions. `admin` owns product improvement intake. | accepted |
| C-004 | The admin mailbox must not require all agents to broadcast product complaints to `everyone`. | accepted |
| C-005 | The role must work when multiple admin-role agents are active in the same shared worktree. | accepted |
| C-006 | The reserved `admin` postbox must stay a separate intake address; configuring an agent with `role = "admin"` must not rename that agent to `admin` or implicitly merge its personal inbox with the shared postbox. | accepted |

## Success criteria

| ID | Outcome |
|---|---|
| SC-001 | Another agent can send a product bug or improvement request to the reserved `admin` postbox and know that is the correct destination. |
| SC-002 | An admin-role agent can review the reserved admin intake and produce a prioritized list of improvement opportunities for the human. |
| SC-003 | Admin-role agents can create Spec Kitty missions from selected opportunities without losing the original requester context. |
| SC-004 | Mission start and finish include a mailbox/coordination check so active agents do not unknowingly collide. |
| SC-005 | Resolved requests get a response or status note explaining the outcome. |
| SC-006 | An agent configured with `role = "admin"` can ask for its role description and receive concrete instructions for admin mailbox triage and mission setup. |
| SC-007 | A non-admin agent can inspect the standing `admin` profile and understand what kinds of mailbox-product reports belong there. |
| SC-008 | `doc/runbook/admin.md` explains admin invariants, intake categories, human prioritization, mission setup, shared-worktree coordination, and finish-time reporting. |
| SC-009 | Acceptance tests or documented experiments prove that an admin-role agent's personal inbox and the reserved `admin` postbox remain distinct. |
| SC-010 | CLI and MCP role-description surfaces return the same admin role guidance for an admin-role session and for an ordinary agent explicitly querying `admin`. |

## Proposed work-package slices

| ID | Slice | Acceptance focus |
|---|---|---|
| WP01 | Role guidance resolution | CLI and MCP both return admin role guidance for own-role and explicit `admin` queries. |
| WP02 | Prompt and onboarding wording | Startup guidance distinguishes `role = "admin"` from the reserved `admin` postbox in compact, actionable language. |
| WP03 | Admin handbook integration | Runtime role guidance exposes or links the durable `doc/runbook/admin.md` material without overloading startup prompts. |
| WP04 | Role/postbox acceptance tests | Tests prove personal admin-role inboxes and the reserved `admin` postbox remain separate while admin role guidance remains discoverable. |

## Out of scope

- Giving `admin` authority to change project priorities without human approval.
- Turning the host role into a product triage role.
- Building a full external issue tracker.
- Making mailbox messages trusted commands.
- Treating every admin-role agent's personal inbox as the reserved `admin` postbox.
