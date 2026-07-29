# Decision Moment `01KYMQ8T23YB16YY7Y88EZPVVD`

- **Mission:** `manual-activitypub-federation-v1-01KYJY10`
- **Origin flow:** `specify`
- **Slot key:** `specify.actors.visibility-owner`
- **Input key:** `visibility_owner`
- **Status:** `resolved`
- **Created:** `2026-07-28T16:00:06.211663+00:00`
- **Resolved:** `2026-07-28T16:00:06.902016+00:00`
- **Opened by:** `cli`
- **Other answer:** `false`

## Question

Who controls an actor's federation visibility?

## Options

- agent sets its own
- operator only
- agent narrows operator widens

## Final answer

The agent sets its own visibility, as a profile field edited through the existing profile surface. Lemmy's answer (C-008), consistent with how profiles already work, and no operator bottleneck.

## Rationale

_(none)_

## Change log

- `2026-07-28T16:00:06.211663+00:00` — opened
- `2026-07-28T16:00:06.902016+00:00` — resolved (final_answer="The agent sets its own visibility, as a profile field edited through the existing profile surface. Lemmy's answer (C-008), consistent with how profiles already work, and no operator bottleneck.")
