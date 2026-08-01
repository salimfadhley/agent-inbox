"""Drive two containerised hubs through everything federation can do so far.

Run the compose file first; see the header there for why containers earn their keep
over the in-process harness and the localhost demo.

This is a **script, not a pytest module**, deliberately. It needs Docker, a network and
two images: making it a test would either be skipped everywhere (and rot unnoticed) or
fail the suite on any machine without a daemon. It exits non-zero on failure so CI can
run it as its own job when we want that.
"""

import json
import sys
import urllib.error
import urllib.request

ALPHA = "http://localhost:18101"
BETA = "http://localhost:18102"

#: How the hubs address each other — container names, not localhost. This is the whole
#: point: every other test resolves `localhost`, which is the one hostname that cannot
#: catch a mistake in host matching.
ALPHA_INTERNAL = "http://alpha:8080"
BETA_INTERNAL = "http://beta:8080"

failures: list[str] = []


def check(label: str, got: object, want: object) -> None:
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        print(f"        expected {want!r}")
        print(f"        got      {got!r}")
        failures.append(label)


def call(url: str, method: str = "GET", body: dict | None = None) -> tuple[int, object]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read() or b"null")
    except urllib.error.HTTPError as refused:
        try:
            return refused.code, json.loads(refused.read() or b"null")
        except ValueError:
            return refused.code, None


def main() -> int:
    print("Two hubs, two containers, one network\n")

    print("both hubs are up and know their own names")
    check("alpha knows its name", call(f"{ALPHA}/")[1]["name"], "alpha")
    check("beta knows its name", call(f"{BETA}/")[1]["name"], "beta")

    print("\nneither federates until told to")
    check("alpha federates", call(f"{ALPHA}/")[1]["federates"], False)
    check("beta nodeinfo is silent", call(f"{BETA}/.well-known/nodeinfo")[0], 404)

    print("\nthe insecure opt-in is visible, because a peer is entitled to know")
    check(
        "alpha admits insecure federation",
        call(f"{ALPHA}/doctor")[1]["hub"].get("insecureFederation"),
        True,
    )

    print("\nswitch both on")
    check(
        "alpha enables", call(f"{ALPHA}/hub", "PUT", {"federation": "enabled"})[0], 200
    )
    check("beta enables", call(f"{BETA}/hub", "PUT", {"federation": "enabled"})[0], 200)
    check("alpha now federates", call(f"{ALPHA}/")[1]["federates"], True)

    print("\nnodeinfo answers, over a real hostname that is not localhost")
    status, info = call(f"{BETA}/nodeinfo/2.1")
    check("beta serves nodeinfo", status, 200)
    check("beta says it is agent-inbox", info["software"]["name"], "agent-inbox")
    check(
        "beta advertises insecure transport",
        info["metadata"].get("insecureTransport"),
        True,
    )

    print("\nan agent joins beta, and WebFinger resolves it by container hostname")
    call(f"{BETA}/actors", "POST", {"preferredUsername": "alice"})
    status, finger = call(f"{BETA}/.well-known/webfinger?resource=acct:alice@beta:8080")
    check("webfinger resolves alice", status, 200)
    if status == 200:
        check(
            "the actor link points at beta's real address",
            finger["links"][0]["href"].startswith(BETA_INTERNAL),
            True,
        )

    print("\na stranger sees only the barebones actor document")
    status, actor = call(f"{BETA}/actors/alice")
    check("actor document served", status, 200)
    if status == 200:
        check("no profile leaked", "profile" in actor, False)
        check("a public key is published", "publicKey" in actor, True)

    print("\nbeta accepts no mail from a hub it has not been told to trust")
    status, _ = call(
        f"{BETA}/actors/alice/inbox",
        "POST",
        {
            "type": "Create",
            "id": f"{ALPHA_INTERNAL}/act/1",
            "object": {"type": "Note", "to": ["alice"], "content": "unsigned"},
        },
    )
    check("unsigned delivery refused", status, 422)

    print(f"\n{'FAILED: ' + ', '.join(failures) if failures else 'all checks passed'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
