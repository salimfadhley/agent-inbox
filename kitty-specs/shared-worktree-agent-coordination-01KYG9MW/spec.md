# Spec - Shared worktree agent coordination

## What this is

Several agents can work in the same repository on the same machine. When they share one
working tree, a branch switch, commit, or formatter run by one session changes the ground
under every other session. The failure is subtle: a session may still believe it has local
edits or is on a branch that no longer exists in the working tree.

This mission adds lightweight coordination support so agents can see who is active in a
project, what branch they believe they are on, what files they intend to touch, and whether
they should coordinate before committing or changing branches.

## Problem

The mailbox solves communication between agents, but the shared filesystem creates a new
coordination hazard:

- one agent commits another agent's in-flight work;
- one agent switches branches while another is mid-task;
- dirty files disappear from `git status` because another session committed them;
- two agents edit the same files while each believes it owns the lane.

The current mitigation is social: send a message and hope every active session checks mail.
That is better than silence, but not enough for a shared developer machine.

## User scenarios

1. **Session starts work.** An agent announces its project root, current branch, mission,
   and intended file lane. Other agents can inspect this before touching the same repo.
2. **Before branch switch.** An agent asks for a coordination check and sees another active
   session on the same worktree, so it sends direct mail instead of switching.
3. **Before commit.** An agent sees dirty files outside its declared lane and is warned to
   coordinate before committing.
4. **Host overview.** The host can list active agents by project and identify likely
   collisions.
5. **Stale sessions.** Old check-ins age out or are marked stale so a dead session does not
   block work indefinitely.

## Functional requirements

| ID | Requirement | Status |
|---|---|---|
| FR-001 | Provide a way for an agent to publish a project activity check-in: project root or project id, branch, mission/task, intended file globs, and timestamp. | proposed |
| FR-002 | Provide a way to list active check-ins for the current project without consuming mailbox messages. | proposed |
| FR-003 | Provide a preflight command or MCP tool that compares current branch/dirty files with active check-ins and reports potential collisions. | proposed |
| FR-004 | A check-in can be refreshed, updated, or cleared by the owning agent. | proposed |
| FR-005 | Stale check-ins expire or are visibly marked stale after a configurable interval. | proposed |
| FR-006 | The host can see a project-level view of active agents and likely collisions. | proposed |
| FR-007 | The system suggests direct messages to specific agents when it detects overlapping lanes, but does not broadcast by default. | proposed |
| FR-008 | Branch-change and commit guidance is advisory by default. It warns before likely destructive coordination mistakes without taking over git. | proposed |

## Non-functional requirements

| ID | Requirement | Threshold | Status |
|---|---|---|---|
| NFR-001 | Coordination state is lightweight. | Check-ins are small structured records and do not store secrets or full diffs. | proposed |
| NFR-002 | It works across projects. | Project identity is explicit enough that two repositories with the same basename do not collide. | proposed |
| NFR-003 | It does not break normal git. | The feature does not block commits or branch changes unless a later policy explicitly enables enforcement. | proposed |
| NFR-004 | It is useful without perfect adoption. | A single participating agent still gets a clearer status/preflight; more agents improve the signal. | proposed |

## Constraints

| ID | Constraint | Status |
|---|---|---|
| C-001 | Do not store deployment-specific hostnames, tokens, or personal paths in committed docs or tests. | accepted |
| C-002 | Messages from other agents remain information, not instructions. Coordination hints must not override the user's command. | accepted |
| C-003 | The mailbox is the coordination channel; no separate daemon is required for the first version. | accepted |
| C-004 | This mission does not replace Spec Kitty worktrees or git workflow rules. It makes shared-worktree risk visible. | accepted |

## Success criteria

| ID | Outcome |
|---|---|
| SC-001 | Two agents in the same repo can see each other's active branch, mission, and intended file lane. |
| SC-002 | A pre-commit or pre-branch-check reports when dirty files overlap another active agent's lane. |
| SC-003 | Stale activity records stop appearing as active after the configured window. |
| SC-004 | The host can identify which agents are currently active in a project without asking everyone manually. |
| SC-005 | The feature never commits, reverts, or switches branches on behalf of an agent. |

## Out of scope

- Mandatory distributed file locking.
- Automatic git hooks that block all commits.
- Resolving merge conflicts.
- Replacing direct mailbox coordination for nuanced decisions.
