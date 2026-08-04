"""The feed component, tested for what a test suite can honestly see.

There is no browser here, so "does the wash actually decay" is not a question pytest can
answer, and pretending otherwise would be worse than admitting it — a green suite that
proved nothing about the thing it named. What *is* checkable, and what a refactor could
silently break:

* the assets are served, same-origin and vendored, so the CSP keeps standing;
* every connection state the relay can publish has a distinct rendered look, so a
  dropped one cannot silently collapse into another;
* nothing in the script infers connection state from a timer, which is the one way
  FR-016 gets lost while every other test stays green;
* reduced motion still distinguishes a new row.

The visual half is verified by loading the deployed page, and that is recorded as a
manual step rather than implied by these passing.
"""

from pathlib import Path

import pytest
from litestar.testing import TestClient

from agent_inbox.client import Config, HubClient
from agent_inbox.console import STATIC_DIR, build_console
from agent_inbox.relay import State


@pytest.fixture(scope="module")
def script() -> str:
    return (STATIC_DIR / "feed.js").read_text()


@pytest.fixture(scope="module")
def styles() -> str:
    return (STATIC_DIR / "feed.css").read_text()


def test_both_assets_exist() -> None:
    for name in ("feed.js", "feed.css"):
        assert (STATIC_DIR / name).is_file(), f"{name} is not vendored"


def test_the_console_will_serve_them() -> None:
    """Served, same-origin, and without a session — `/static/` is an open prefix.

    Written against the running app rather than against the allow-list dict, because a
    file added to the dict and never placed on disk would satisfy the dict and 500 here.
    """
    console = build_console(
        HubClient(Config(hub="http://hub.invalid", name="jed_smith"))
    )
    with TestClient(app=console) as client:
        for name, kind in (("feed.js", "javascript"), ("feed.css", "css")):
            response = client.get(f"/static/{name}")
            assert response.status_code == 200, f"/static/{name} is not served"
            assert kind in response.headers["content-type"]
            assert response.content, f"/static/{name} served an empty body"


def test_nothing_is_fetched_from_another_host(script: str, styles: str) -> None:
    """`connect-src 'self'` and `script-src 'self'` must keep standing.

    A single CDN reference would be blocked at runtime by the CSP and would show up as
    a page that silently does nothing, which is the hardest kind of breakage to trace.
    """
    for source in (script, styles):
        assert "http://" not in source
        assert "https://" not in source
        assert "//cdn" not in source


@pytest.mark.parametrize("state", [s.value for s in State])
def test_every_relay_state_is_rendered_distinctly(
    state: str, script: str, styles: str
) -> None:
    """A state the relay can publish and the page cannot show is a silent dead end."""
    assert state in script, f"the script never handles state {state!r}"
    assert state in styles, f"the stylesheet gives state {state!r} no distinct look"


def test_the_states_do_not_share_wording(script: str) -> None:
    """The paired positive: three states must read as three different things."""
    for words in ("Line open", "Reconnecting", "Line lost"):
        assert words in script
    assert script.count("Line open") == 1


def test_the_script_never_infers_the_connection_state(script: str) -> None:
    """FR-016, guarded where it is most likely to be lost.

    A page that concluded "no events lately, so we must be disconnected" — or the
    reverse — would make the head row confidently wrong, and from the browser a quiet
    hub and a dead connection are the same silence. Only the relay knows which.

    So there must be exactly one timer in this file, and it must be the clock.
    """
    code = _without_comments(script)
    assert code.count("setInterval") == 1, "a second timer appeared; what does it do?"
    assert code.count("setTimeout") == 0
    # The two handlers that could plausibly reintroduce the guess. Checked against code
    # with comments stripped, because the script *documents* why it has no `onerror` —
    # and the first version of this test failed on that sentence, which is a test
    # reading prose rather than behaviour.
    assert ".onerror" not in code
    assert 'addEventListener("error"' not in code


def test_direction_is_carried_in_words_as_well_as_colour(script: str) -> None:
    """FR-013. Someone who cannot separate the hues must still read the direction."""
    assert '"from"' in script
    assert '"to"' in script


def test_both_colour_schemes_define_both_directions(styles: str) -> None:
    assert "prefers-color-scheme: dark" in styles
    # Twice each: once for light, once for dark. A single definition means one scheme
    # inherits the other's hue and the pair stops being complementary.
    assert styles.count("--in:") >= 2
    assert styles.count("--out:") >= 2


def test_reduced_motion_still_marks_a_new_row(styles: str) -> None:
    """Removing the movement must not remove the meaning.

    The weight is the console's existing vocabulary for unread, so this borrows a
    meaning readers already have rather than inventing a second one.
    """
    assert "prefers-reduced-motion: reduce" in styles
    block = styles.split("prefers-reduced-motion: reduce", 1)[1]
    assert "animation: none" in block
    assert "font-weight" in block, "reduced motion left a new row indistinguishable"


def test_hidden_rows_are_retained_not_removed(script: str) -> None:
    """Switching a filter back must show what arrived while it was hidden."""
    assert "row.hidden" in script
    assert "removeChild(this.rows.lastChild)" in script  # only the overflow cap removes


def test_the_subject_is_set_as_text_never_as_markup(script: str) -> None:
    """A subject is somebody else's words, and this page is rendered for an operator."""
    assert "innerHTML" not in script
    assert "textContent" in script


def test_it_subscribes_to_the_consoles_own_origin(script: str) -> None:
    """Not to the hub. That is what keeps `connect-src 'self'` true and what makes N
    viewers cost the hub one listener."""
    assert 'EventSource("/events")' in script


def test_the_row_cap_is_bounded(script: str) -> None:
    """An unbounded list is a memory leak that presents as a working page."""
    assert "MAX_ROWS" in script
    cap = int(script.split("MAX_ROWS =", 1)[1].split(";", 1)[0].strip())
    assert 0 < cap <= 1000


def test_the_asset_allowlist_is_still_an_allowlist() -> None:
    """The static route serves a named set, so it cannot be walked into the tree."""
    source = Path(STATIC_DIR).parent.joinpath("console.py").read_text()
    allowed = source.split("allowed = {", 1)[1].split("}", 1)[0]
    assert "feed.js" in allowed
    assert "feed.css" in allowed
    assert ".." not in allowed


def _without_comments(source: str) -> str:
    """The script with `/* … */` and `// …` removed.

    Crude, and sufficient: this file contains no string literal holding a comment
    marker, and the alternative — asserting against prose — is what produced a failing
    test on a correct implementation the first time round.
    """
    out: list[str] = []
    rest = source
    while "/*" in rest:
        head, _, tail = rest.partition("/*")
        out.append(head)
        _, _, rest = tail.partition("*/")
    out.append(rest)
    lines = "".join(out).split("\n")
    return "\n".join(line.partition("//")[0] for line in lines)
