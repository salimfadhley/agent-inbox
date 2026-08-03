"""Names: canonical form, adjudication, and even distribution (M1, FR-002/FR-003)."""

from collections import Counter

import pytest

from agent_inbox.exceptions import NameUnavailable
from agent_inbox.name_pool import FAMILY_NAMES, GIVEN_NAMES, NAME_POOL
from agent_inbox.naming import (
    RESERVED_NAMES,
    Name,
    generate,
    normalize,
    validate,
    validate_hub_name,
)


class TestNormalize:
    def test_produces_ascii_lowercase_underscored(self) -> None:
        assert normalize("Trevor Mahmood") == "trevor_mahmood"
        assert normalize("  Yitsac   Ping  ") == "yitsac_ping"
        assert normalize("O'Brien-Smith") == "o_brien_smith"

    def test_folds_latin_diacritics(self) -> None:
        assert normalize("Zoë Müller") == "zoe_muller"
        assert normalize("José Antônio") == "jose_antonio"

    def test_non_ascii_scripts_reduce_to_nothing_and_are_refused(self) -> None:
        """Strictly ASCII is the owner's ruling, so these are refused, not guessed at.

        Silently transliterating would hand an agent a name it did not choose, and a
        machine reading of a name is often simply wrong.
        """
        for source in ("Владимир", "田中", "مُحَمَّد"):
            with pytest.raises(NameUnavailable, match="romanised"):
                validate(source)

    def test_canonical_form_prevents_collisions(self) -> None:
        """Two spellings of one name must not become two actors."""
        assert normalize("Zoë Müller") == normalize("zoe_muller")


class TestValidate:
    def test_accepts_a_normal_name(self) -> None:
        assert validate("Trevor Mahmood") == Name("trevor_mahmood")

    @pytest.mark.parametrize("reserved", sorted(RESERVED_NAMES))
    def test_refuses_reserved_words(self, reserved: str) -> None:
        """`local` in particular is an addressing guarantee, not a name."""
        with pytest.raises(NameUnavailable, match="reserved"):
            validate(reserved)

    def test_refuses_a_name_with_nothing_usable(self) -> None:
        with pytest.raises(NameUnavailable, match="no usable characters"):
            validate("!!! ???")

    def test_refuses_an_over_long_name(self) -> None:
        with pytest.raises(NameUnavailable, match="not a usable name"):
            validate("x" * 65)

    def test_errors_say_what_to_do(self) -> None:
        """An agent reads these, so they must be actionable, not just refusals."""
        with pytest.raises(NameUnavailable) as exc:
            validate("local")
        assert "reserved" in str(exc.value)


class TestGenerate:
    def test_generated_names_are_always_valid(self) -> None:
        for seed in range(300):
            validate(generate(seed=seed))  # raises if not

    def test_is_deterministic_for_a_seed(self) -> None:
        assert generate(seed=42) == generate(seed=42)

    def test_names_look_like_names(self) -> None:
        name = generate(seed=1)
        assert "_" in name, "a name is given plus family"
        assert name.islower() and name.isascii()

    def test_names_cross_traditions(self) -> None:
        """ "Rosemary Nasrin" is the target, not "Aino Auvinen".

        Given and family names are drawn independently, so most pairs span two
        traditions. Pairing within a tradition would be tidier and duller.
        """
        by_given = {n: t for t, (given, _) in NAME_POOL.items() for n in given}
        by_family = {n: t for t, (_, family) in NAME_POOL.items() for n in family}
        crossed = 0
        for seed in range(200):
            given, _, family = generate(seed=seed).partition("_")
            if by_given.get(given) != by_family.get(family):
                crossed += 1
        assert crossed > 150, f"only {crossed}/200 names crossed traditions"

    def test_no_tradition_dominates(self) -> None:
        """Even distribution is required — a fleet of English names is the bug."""
        by_given = {n: t for t, (given, _) in NAME_POOL.items() for n in given}
        counts = Counter(
            by_given[generate(seed=s).partition("_")[0]] for s in range(3000)
        )
        fair = 1 / len(NAME_POOL)
        for tradition, n in counts.items():
            share = n / 3000
            assert share < 2.5 * fair, f"{tradition} took {share:.1%} (fair {fair:.1%})"
        assert len(counts) == len(NAME_POOL), "every tradition should appear"

    def test_every_pooled_name_is_already_canonical(self) -> None:
        """The pool is checked in, so a bad entry is a permanent bug."""
        for word in (*GIVEN_NAMES, *FAMILY_NAMES):
            assert word == normalize(word), f"{word!r} is not canonical"
            assert sum(c in "aeiou" for c in word) >= 1, f"{word!r} is not legible"

    def test_no_generated_name_is_reserved(self) -> None:
        assert not {generate(seed=s) for s in range(500)} & RESERVED_NAMES


class TestHubNameValidation:
    """The right-hand side of `name@hub`, which was validated nowhere until now."""

    @pytest.mark.parametrize(
        "name", ["saltclub", "local", "a", "a1", "salt_club", "s" * 64, "hub2"]
    )
    def test_accepted(self, name: str) -> None:
        assert validate_hub_name(name) == name

    def test_local_is_permitted_here(self) -> None:
        """The default, and a real name. What it blocks is *enabling federation*, and
        that rule lives where the consequence is — not in the validator."""
        assert validate_hub_name("local") == "local"

    def test_a_hostname_is_refused_as_a_name(self) -> None:
        """The conflation this mission exists to remove, so it earns its own test."""
        with pytest.raises(NameUnavailable) as caught:
            validate_hub_name("hub.example.com")
        message = str(caught.value)
        assert "address" in message and "name" in message

    def test_spaces_and_capitals_are_refused_not_normalised(self) -> None:
        """Reshaping this into `the_salt_club` is what happens today, and is the
        defect: an operator should learn the rule, not be handed a name they did not
        choose."""
        with pytest.raises(NameUnavailable):
            validate_hub_name("The Salt Club")

    @pytest.mark.parametrize(
        "name", ["", "   ", "_saltclub", "saltclub_", "s" * 65, "SALTCLUB", "salt-club"]
    )
    def test_refused(self, name: str) -> None:
        with pytest.raises(NameUnavailable):
            validate_hub_name(name)

    def test_the_message_states_the_rule(self) -> None:
        with pytest.raises(NameUnavailable) as caught:
            validate_hub_name("Salt Club")
        assert "saltclub" in str(caught.value)

    def test_one_rule_shared_with_agent_names(self) -> None:
        """If the two ever diverge, this is what says so.

        Every input here is one the *pattern* decides, so both validators must agree.
        Inputs where they legitimately differ — `local`, and anything needing
        normalisation — are excluded deliberately and tested above.
        """
        canonical = ["saltclub", "a", "s" * 64, "salt_club", "a1"]
        for case in canonical:
            assert normalize(case) == case, "test input is not canonical"
            assert validate_hub_name(case) == validate(case).value

        # Refusals must be compared in canonical form too. `_leading` is not a useful
        # case here: `validate` normalises it to `leading` and accepts, which is the
        # deliberate difference between the two, not a divergence in the rule.
        for case in ["s" * 65, ""]:
            assert normalize(case) == case.strip("_"), "test input is not canonical"
            with pytest.raises(NameUnavailable):
                validate_hub_name(case)
            with pytest.raises(NameUnavailable):
                validate(case)
