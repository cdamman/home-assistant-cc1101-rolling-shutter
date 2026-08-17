"""Tests for the shutter ID helpers."""
from __future__ import annotations

import pytest

from custom_components.cc1101_rolling_shutter.const import (
    is_shutter_id,
    normalise_shutter_id,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("12345600", "12345600"),
        ("12:34:56:00", "12345600"),
        ("12-34-56-00", "12345600"),
        ("12.34.56.00", "12345600"),
        ("  12 34 56 00  ", "12345600"),
        ("0A1B2C01", "0a1b2c01"),
    ],
)
def test_separators_and_case_are_normalised(raw: str, expected: str) -> None:
    """Any accepted spelling maps to 8 lowercase hex digits."""
    assert normalise_shutter_id(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "4",  # the index used by the pre-protocol firmware
        "1234560",  # 7 digits
        "123456000",  # 9 digits
        "12345g00",  # not hex
        "12345600ff",
        "0x12345600",
    ],
)
def test_invalid_ids_are_rejected(raw: str) -> None:
    """Anything that is not a 4-byte identifier raises."""
    with pytest.raises(ValueError):
        normalise_shutter_id(raw)
    assert not is_shutter_id(raw)


def test_is_shutter_id_accepts_valid_ids() -> None:
    """The predicate mirrors the parser."""
    assert is_shutter_id("12:34:56:00")
    assert is_shutter_id("12345600")
