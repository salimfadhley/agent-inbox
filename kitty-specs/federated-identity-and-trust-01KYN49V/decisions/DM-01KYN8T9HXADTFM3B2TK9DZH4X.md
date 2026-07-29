# Decision Moment `01KYN8T9HXADTFM3B2TK9DZH4X`

- **Mission:** `federated-identity-and-trust-01KYN49V`
- **Origin flow:** `specify`
- **Slot key:** `specify.surface.operator-client`
- **Input key:** `operator_surface`
- **Status:** `resolved`
- **Created:** `2026-07-28T21:06:44.926013+00:00`
- **Resolved:** `2026-07-28T21:06:45.749738+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

Does the operator surface belong in this mission, or is CLI-only enough?

## Options

- CLI only
- console section
- both minimal

## Final answer

CLI only. ADR 0005 already makes the CLI a first-class client. Removes the dependency on issue #21's Settings re-org, keeps the mission pure backend plus CLI, and makes it smaller and likelier to converge. The console section becomes its own mission after #21.

## Rationale

_(none)_

## Change log

- `2026-07-28T21:06:44.926013+00:00` — opened
- `2026-07-28T21:06:45.749738+00:00` — resolved (final_answer="CLI only. ADR 0005 already makes the CLI a first-class client. Removes the dependency on issue #21's Settings re-org, keeps the mission pure backend plus CLI, and makes it smaller and likelier to converge. The console section becomes its own mission after #21.")
