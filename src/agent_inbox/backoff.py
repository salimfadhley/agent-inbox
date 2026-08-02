"""How long to wait before trying a dropped connection again.

Its own module because two very different clients need the same answer and must not
import each other. The MCP server holds a stream for the life of a session and reaches
it through `httpx`; the wake hook holds one for the life of a wait and reaches it
through `urllib`, because `httpx` lives in the `clients` extra and the base CLI must not
drag it in. Duplicating the function would have duplicated the reasoning below, which is
the part worth keeping in one place.
"""

import random
from collections.abc import Callable

#: The first delay, and the ceiling the doubling stops at.
RECONNECT_FIRST = 1.0
RECONNECT_CAP = 60.0

#: How long a connection must last before it counts as having worked. Below this it is
#: treated as another failure, however cleanly it opened.
SETTLED_AFTER = 30.0


def reconnect_delay(
    attempt: int, *, rand: Callable[[], float] = random.random
) -> float:
    """How long to wait before the next attempt. Exponential, capped, fully jittered.

    **The jitter is the part that matters**, and it is the part usually left out. A hub
    is redeployed several times a day, and every release drops every connected client in
    the same instant. Without jitter they all wait one second, all reconnect together,
    and the hub's first act on coming up is to serve a thundering herd it created itself
    — repeatedly, since a herd that fails together retries together.

    Full jitter (uniform between zero and the ceiling) rather than a small wobble around
    it: it spreads a simultaneous disconnect across the whole window, and the cost — an
    occasional short wait — is a client reconnecting sooner than it strictly had to.
    """
    ceiling = min(RECONNECT_CAP, RECONNECT_FIRST * (2**attempt))
    return ceiling * rand()
