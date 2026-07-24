# Tasks — CLI as the primary agent client

**Mission**: `cli-primary-client-01KYA42E` · **Branch**: `feat/cli-primary-client`
**Spec**: [spec.md](./spec.md) · **Plan**: [plan.md](./plan.md)

Six work packages. WP01 and WP02 are independent and start together; everything else
follows the dependency column. The removal (WP05) lands last, after its replacement is
proven, and the migration broadcast (WP06) happens **before** the removal deploys.

| WP | Title | Depends on | Subtasks | Requirements |
|---|---|---|---|---|
| WP01 | Hub HTTP API | — | 6 | FR-001, C-002, C-007 |
| WP02 | Config file and identity inference | — | 5 | FR-005, FR-006, FR-007, FR-008 |
| WP03 | HTTP client library | WP01, WP02 | 4 | FR-004, NFR-002 |
| WP04 | CLI rewritten onto the API | WP03 | 6 | FR-004, FR-009, NFR-003 |
| WP05 | stdio MCP proxy, and hosted MCP removed | WP04 | 6 | FR-002, FR-003, NFR-001 |
| WP06 | Prompts, migration broadcast, deploy | WP05 | 5 | FR-010, NFR-004, C-004, C-006 |

## Subtask index

| ID | Description | WP | Parallel |
|---|---|---|---|
| T001 | Add `fastapi` + `httpx` to dependencies; confirm gates still green | WP01 | |
| T002 | `api.py`: app factory, `/api/v1` router, identity header dependency | WP01 | |
| T003 | Mail routes: send, inbox, read, reply, unread count | WP01 | |
| T004 | Directory + thread routes: agents, whois, register, threads, read-thread | WP01 | [P] |
| T005 | Error mapping: `MailboxError`/`ConfigError` → status codes with usable detail | WP01 | [P] |
| T006 | `test_api.py`: route coverage, including that no route exposes `Mailbox.thread` | WP01 | |
| T007 | `conf_file.py`: locate `agent-inbox.toml` by walking up to the git root | WP02 | |
| T008 | Inference: project from git toplevel, agent from engine, role `agent` | WP02 | |
| T009 | Provenance — each inferred value records where it came from | WP02 | [P] |
| T010 | `init` writer: non-interactive, `--hub` required, all else overridable | WP02 | |
| T011 | `test_conf_file.py`: discovery, inference, provenance, init round-trip | WP02 | |
| T012 | `client.py`: `HubClient` over httpx with identity header and timeouts | WP03 | |
| T013 | Map HTTP failures to actionable errors; never raise a bare httpx error | WP03 | |
| T014 | One method per API operation, returning the same models the CLI prints | WP03 | |
| T015 | `test_client.py`: timeout, connection refused, 4xx/5xx mapping | WP03 | |
| T016 | Rewrite mail commands (`send`, `inbox`, `read`, `reply`, `notify`, `ping`) | WP04 | |
| T017 | Rewrite directory commands (`agents`, `whois`, `register`, `hub-info`) | WP04 | [P] |
| T018 | Delete every SQLite code path from the CLI, including `--db` | WP04 | |
| T019 | No-config UX: print inferred identity with sources, exit non-zero, no hub call | WP04 | |
| T020 | `doctor`: config → hub reachable → registered → tools servable, each with a fix | WP04 | |
| T021 | Rewrite `test_cli.py` against a stub hub; assert the CLI never opens a database | WP04 | |
| T022 | `stdio_proxy.py`: stdio MCP server exposing today's 12 tool names | WP05 | |
| T023 | Each tool maps to exactly one client call — no routing logic in the proxy | WP05 | |
| T024 | `mcp-serve` runs the stdio proxy; hosted-transport flags removed | WP05 | |
| T025 | Remove `build_http_app`'s MCP mount; serve API + console only | WP05 | |
| T026 | Assert the hosted MCP endpoint is gone, and tool names are unchanged | WP05 | |
| T027 | Measure proxy overhead against NFR-001 on a running hub | WP05 | |
| T028 | Rewrite `agent.md`, `host.md`, `admin.md` for install → init → mcp add | WP06 | |
| T029 | Update `/ui/prompts` short-form copy blocks to match | WP06 | [P] |
| T030 | Broadcast migration instructions **while hosted MCP still works** | WP06 | |
| T031 | Release, deploy to the hub, `uv tool install` locally | WP06 | |
| T032 | Verify against a copy of live hub data; confirm a real agent round-trip | WP06 | |

---

## WP01 — Hub HTTP API

**Goal**: the hub speaks HTTP for every mail operation, shaped so the console (mission
0021) and hand-written `curl` clients can use it later without changes.
**Independent test**: `TestClient` completes send → inbox → read → reply without MCP.

- [ ] T001 Add `fastapi` + `httpx` to dependencies; confirm gates still green (WP01)
- [ ] T002 `api.py`: app factory, `/api/v1` router, identity header dependency (WP01)
- [ ] T003 Mail routes: send, inbox, read, reply, unread count (WP01)
- [ ] T004 Directory + thread routes: agents, whois, register, threads, read-thread (WP01)
- [ ] T005 Error mapping: `MailboxError`/`ConfigError` → status codes with usable detail (WP01)
- [ ] T006 `test_api.py`: route coverage, including that no route exposes `Mailbox.thread` (WP01)

**Risks**: exposing the omniscient `Mailbox.thread()` by accident would re-open mission
0020 hub-wide. T006 asserts against it explicitly.

## WP02 — Config file and identity inference

**Goal**: an agent with no configuration is told exactly who it would be, where each part
came from, and the one command that writes it.
**Independent test**: in a temp git repo, inference yields the repo name and `init` writes
a file that round-trips.

- [ ] T007 `conf_file.py`: locate `agent-inbox.toml` by walking up to the git root (WP02)
- [ ] T008 Inference: project from git toplevel, agent from engine, role `agent` (WP02)
- [ ] T009 Provenance — each inferred value records where it came from (WP02)
- [ ] T010 `init` writer: non-interactive, `--hub` required, all else overridable (WP02)
- [ ] T011 `test_conf_file.py`: discovery, inference, provenance, init round-trip (WP02)

**Notes**: no interactive prompting anywhere — agents drive non-interactive shells, and a
prompt that waits is how the codex CLI stalled for 40 minutes.

## WP03 — HTTP client library

**Goal**: one client both the CLI and the proxy use, which can never hang a turn.
**Independent test**: against a stub server — success, timeout, refused, 404, 500.

- [ ] T012 `client.py`: `HubClient` over httpx with identity header and timeouts (WP03)
- [ ] T013 Map HTTP failures to actionable errors; never raise a bare httpx error (WP03)
- [ ] T014 One method per API operation, returning the same models the CLI prints (WP03)
- [ ] T015 `test_client.py`: timeout, connection refused, 4xx/5xx mapping (WP03)

## WP04 — CLI rewritten onto the API

**Goal**: every command reaches the hub over HTTP, and no CLI code path opens SQLite.
**Independent test**: the full command surface against a stub hub, with a test asserting
no database file is ever opened.

- [ ] T016 Rewrite mail commands (`send`, `inbox`, `read`, `reply`, `notify`, `ping`) (WP04)
- [ ] T017 Rewrite directory commands (`agents`, `whois`, `register`, `hub-info`) (WP04)
- [ ] T018 Delete every SQLite code path from the CLI, including `--db` (WP04)
- [ ] T019 No-config UX: print inferred identity with sources, exit non-zero, no hub call (WP04)
- [ ] T020 `doctor`: config → hub reachable → registered → tools servable, each with a fix (WP04)
- [ ] T021 Rewrite `test_cli.py` against a stub hub; assert the CLI never opens a database (WP04)

**Risks**: this is the widest behavioural change. Tool names and output shapes are frozen;
only the transport moves.

## WP05 — stdio MCP proxy, and hosted MCP removed

**Goal**: agents connect through a local stdio server, and the hosted endpoint is gone.
**Independent test**: an MCP client speaking stdio to `agent-inbox mcp-serve` completes a
send/read cycle; a request to the old hosted path 404s.

- [ ] T022 `stdio_proxy.py`: stdio MCP server exposing today's 12 tool names (WP05)
- [ ] T023 Each tool maps to exactly one client call — no routing logic in the proxy (WP05)
- [ ] T024 `mcp-serve` runs the stdio proxy; hosted-transport flags removed (WP05)
- [ ] T025 Remove `build_http_app`'s MCP mount; serve API + console only (WP05)
- [ ] T026 Assert the hosted MCP endpoint is gone, and tool names are unchanged (WP05)
- [ ] T027 Measure proxy overhead against NFR-001 on a running hub (WP05)

## WP06 — Prompts, migration broadcast, deploy

**Goal**: agents can migrate themselves, and the change reaches the hub safely.
**Independent test**: an agent given only the prompt URL reaches a working `ping`.

- [ ] T028 Rewrite `agent.md`, `host.md`, `admin.md` for install → init → mcp add (WP06)
- [ ] T029 Update `/ui/prompts` short-form copy blocks to match (WP06)
- [ ] T030 Broadcast migration instructions **while hosted MCP still works** (WP06)
- [ ] T031 Release, deploy to the hub, `uv tool install` locally (WP06)
- [ ] T032 Verify against a copy of live hub data; confirm a real agent round-trip (WP06)

**Ordering is load-bearing**: T030 must complete *before* T031 deploys the removal, or
agents lose access with no instructions (C-004).
