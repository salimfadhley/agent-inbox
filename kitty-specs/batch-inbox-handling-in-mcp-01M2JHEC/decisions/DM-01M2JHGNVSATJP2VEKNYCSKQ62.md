# Decision Moment `01M2JHGNVSATJP2VEKNYCSKQ62`

- **Mission:** `batch-inbox-handling-in-mcp-01M2JHEC`
- **Origin flow:** `specify`
- **Slot key:** `specify.retry.design`
- **Input key:** `retry_design`
- **Status:** `resolved`
- **Created:** `2026-09-15T12:43:51.033078+00:00`
- **Resolved:** `2026-09-15T12:43:51.744089+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

Where does safe retry after a lost response live: client-side lookup of the caller's own reply, or hub-side idempotency keys?

## Options

- Client-side lookup
- Hub-side idempotency keys
- Both, client first

## Final answer

Client-side lookup

## Rationale

_(none)_

## Change log

- `2026-09-15T12:43:51.033078+00:00` — opened
- `2026-09-15T12:43:51.744089+00:00` — resolved (final_answer="Client-side lookup")
