"""Token normalization (ADR-003).

A pure function, so it is tested exhaustively against a table of inputs. The
last group of cases is the important one: it pins down what normalization
deliberately *cannot* do, which is the reason the alias column exists.
"""

from __future__ import annotations

import pytest

from app.canonical import is_canonical_token, normalize_token, tokenize


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("iPhone 16", "iphone_16"),
        ("iphone 16", "iphone_16"),
        ("IPHONE 16", "iphone_16"),
        ("  iPhone   16  ", "iphone_16"),
        ("iPhone-16", "iphone_16"),
        ("iPhone.16", "iphone_16"),
        ("iPhone_16", "iphone_16"),
        ("MacBook Air M3", "macbook_air_m3"),
        ("USB-C", "usb_c"),
        ("Phone Cases", "phone_cases"),
        ("Chargers & Adapters", "chargers_adapters"),
        # Accents are folded rather than dropped.
        ("Café", "cafe"),
        ("naïve", "naive"),
        # Leading and trailing separators are trimmed.
        ("--iphone--16--", "iphone_16"),
        ("!!!", ""),
        ("", ""),
    ],
)
def test_normalization_cases(raw: str, expected: str) -> None:
    assert normalize_token(raw) == expected


def test_normalization_is_idempotent() -> None:
    for raw in ("iPhone 16", "MacBook Air M3", "USB-C", "Chargers & Adapters"):
        once = normalize_token(raw)
        assert normalize_token(once) == once


def test_normalization_alone_cannot_bridge_a_missing_separator() -> None:
    """The reason ``compatibility_targets.aliases`` exists (ADR-003).

    A buyer who writes "iphone16" produces a token that is well-formed and
    wrong. No amount of normalization turns it into ``iphone_16``; only an
    alias does.
    """
    assert normalize_token("iphone16") == "iphone16"
    assert normalize_token("iphone16") != normalize_token("iPhone 16")


def test_canonical_token_shape() -> None:
    for good in ("iphone_16", "usb_c", "phone_case", "macbook_air_m3", "a1", "2_5d"):
        assert is_canonical_token(good), good

    for bad in ("iPhone_16", "iphone 16", "_iphone", "iphone_", "iphone__16", "", "iphone.16"):
        assert not is_canonical_token(bad), bad


def test_normalized_output_is_always_canonical_or_empty() -> None:
    samples = [
        "iPhone 16",
        "  USB--C  ",
        "Chargers & Adapters",
        "Café",
        "!!!",
        "",
        "MacBook Air (M3)",
        "20W/30W",
        "2.5D glass",
    ]
    for sample in samples:
        token = normalize_token(sample)
        assert token == "" or is_canonical_token(token), (sample, token)


# --------------------------------------------------------------------------
# tokenize — the relevance scorer's word splitter (M3)
# --------------------------------------------------------------------------


def test_tokenize_splits_normalized_text_into_words() -> None:
    assert tokenize("Slim iPhone-16 case") == ("slim", "iphone", "16", "case")


def test_tokenize_shares_normalization_with_normalize_token() -> None:
    """One implementation of "what is a word here", so the compatibility
    pipeline and the relevance scorer cannot drift apart."""
    assert tokenize("Café  USB-C") == ("cafe", "usb", "c")
    assert "_".join(tokenize("iPhone 16")) == normalize_token("iPhone 16")


def test_tokenize_of_nothing_is_empty_rather_than_a_blank_token() -> None:
    """A blank token would match every product's blank, which is not a match."""
    assert tokenize("???") == ()
    assert tokenize("") == ()
    assert tokenize("   ") == ()


def test_tokenize_does_not_bridge_a_missing_separator() -> None:
    """The same limit `normalize_token` has, for the same reason: `iphone16` is
    not evidence of `iphone 16`, and guessing is what aliases exist to avoid."""
    assert tokenize("iphone16") == ("iphone16",)
