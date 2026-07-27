# Captured wire fixtures

Real responses from real releases, recorded rather than written.

| file | captured from | how |
|---|---|---|
| `inbox-0.16.1.json` | `GET /actors/{name}/inbox` on **v0.16.1** | that tag checked out into a scratch worktree, its own `build_api` run under Litestar's TestClient, response saved verbatim |

**Do not tidy these.** The moment one is edited it stops being a record of what the hub
sent and becomes a record of what somebody thought it sent — which is exactly the
weakness that prompted the capture. ludmila_coe raised it: a compatibility test built
from a hand-written approximation validates your belief about the interface, not the
interface.

Regenerate rather than edit. To redo this one:

```
git worktree add --detach /tmp/v0161 v0.16.1
```

then run that tree's `build_api` against an `InMemoryStore`, join two actors, send a
direct message and a broadcast, and `GET` the recipient's inbox.
