# Decision Moment `01KYMQC8Z4CKN86Y3R79T06BCB`

- **Mission:** `manual-activitypub-federation-v1-01KYJY10`
- **Origin flow:** `specify`
- **Slot key:** `specify.descriptor.disclosure`
- **Input key:** `descriptor_disclosure`
- **Status:** `resolved`
- **Created:** `2026-07-28T16:01:59.780476+00:00`
- **Resolved:** `2026-07-28T16:02:00.454491+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

How much does the unauthenticated peer descriptor disclose?

## Options

- full capabilities
- reachability only
- boolean plus gated detail

## Final answer

Full capabilities, unauthenticated, as FR-017 already asks. Matches nodeinfo across the fediverse (C-008). A peer cannot compatibility-check what it cannot see, which is FR-016's purpose.

## Rationale

_(none)_

## Change log

- `2026-07-28T16:01:59.780476+00:00` — opened
- `2026-07-28T16:02:00.454491+00:00` — resolved (final_answer="Full capabilities, unauthenticated, as FR-017 already asks. Matches nodeinfo across the fediverse (C-008). A peer cannot compatibility-check what it cannot see, which is FR-016's purpose.")
