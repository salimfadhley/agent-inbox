"""Two hubs, over real HTTP, one reading the other.

The demo for federation steps 2 and 3. Run it with::

    uv run python doc/demo/two_hubs.py

It starts two hubs on ports 8101 and 8102. **A** is named `saltclub` and has
federation switched on; **B** is named `pepperclub` and has not.

What it shows, and what each line proves:

- A answers NodeInfo, WebFinger and an actor document. B answers 404 to all of them —
  a hub that has not chosen to federate discloses nothing, not even that a name exists.
- A's actor document has five keys. No `profile`, no `lastSeen`, no `outbox`: a peer
  learns what addressing requires and nothing about what an agent is doing.
- A can ask B who it is, and is refused, because B is not federating.
- A can ask itself and gets software, version, title and roster size.

The test suite covers all of this in-process. This script exists because passing tests
that never crossed a real socket are not proof that two hubs interoperate.
"""

import asyncio
import json
import sys
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, "src")

import uvicorn  # noqa: E402 — after the sys.path shim above, deliberately

from agent_inbox.api import build_api  # noqa: E402
from agent_inbox.house import House  # noqa: E402
from agent_inbox.mailbox import Mailbox  # noqa: E402
from agent_inbox.peers import identify  # noqa: E402
from agent_inbox.store import InMemoryStore  # noqa: E402


def start(name: str, port: int, federating: bool, title: str | None = None):
    """Start one hub on a port, with federation on or off."""
    house = House(Mailbox(InMemoryStore(), hub_name=name))
    if federating:
        asyncio.run(house.mailbox.set_hub_setting("federation", "enabled"))
    if title:
        asyncio.run(house.mailbox.set_hub_setting("title", title))
    asyncio.run(house.join("alice"))
    app = build_api(house, f"http://localhost:{port}")
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    s = uvicorn.Server(config)
    threading.Thread(target=s.run, daemon=True).start()
    return s


a = start("saltclub", 8101, True, "The Salt Club")
b = start("pepperclub", 8102, False)
time.sleep(1.5)


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, None


print("HUB A (saltclub, federating)  HUB B (pepperclub, NOT federating)")
print("-" * 66)
for label, url in (
    ("A nodeinfo index ", "http://localhost:8101/.well-known/nodeinfo"),
    (
        "A webfinger alice",
        "http://localhost:8101/.well-known/webfinger"
        "?resource=acct:alice@localhost:8101",
    ),
    ("A actor alice    ", "http://localhost:8101/actors/alice"),
    ("B nodeinfo index ", "http://localhost:8102/.well-known/nodeinfo"),
    (
        "B webfinger alice",
        "http://localhost:8102/.well-known/webfinger"
        "?resource=acct:alice@localhost:8102",
    ),
):
    code, body = get(url)
    extra = ""
    if body and "links" in body:
        extra = "-> " + body["links"][0]["href"]
    elif body and "preferredUsername" in body:
        extra = "keys: " + ",".join(sorted(body))
    print(f"  {label} {code}  {extra}")

print()
print("A asks B who it is:      ", end="")
try:
    who = identify("http://localhost:8102")
    print(f"{who.software} {who.version}, federating={who.federates}")
except Exception as e:
    print(f"refused — {e}")
print("A asks itself who it is: ", end="")
who = identify("http://localhost:8101")
print(
    f"{who.software} {who.version}, federating={who.federates}, "
    f"title={who.title!r}, agents={who.users}"
)
a.should_exit = True
b.should_exit = True
