import pytest

from app.ages import parse_age_criterion

CASES = [
    ("Age > 18 years", (18, None)),
    ("Age >18", (18, None)),
    ("Patients aged ≥ 18 years", (18, None)),
    ("Age >= 18 years at the time of consent", (18, None)),
    ("Male or female, 18 years of age or older", (18, None)),
    ("18 years or older", (18, None)),
    ("At least 40 years of age", (40, None)),
    ("Older than 18 years", (18, None)),
    ("Age 18 to 75 years, inclusive", (18, 75)),
    ("Aged between 50 and 85 years", (50, 85)),
    ("40-80 years old", (40, 80)),
    ("Age ≥ 18 years and < 75 years", (18, 74)),
    ("≥18 and ≤85 years", (18, 85)),
    ("Age ≥ 40 years and younger than 80", (40, 79)),
    ("Patients must be under 75 years", (None, 74)),
    ("Age ≤ 75 years", (None, 75)),
    ("Up to 65 years of age", (None, 65)),
    ("Age 18 to <75 years", (18, 74)),
    ("Adults aged 40 years and over with COPD", (40, None)),
    ("", (None, None)),
    (None, (None, None)),
    ("Infants aged 6 to 12 months", (None, None)),
]


@pytest.mark.parametrize("text,expected", CASES)
def test_age_criterion(text, expected):
    assert parse_age_criterion(text) == expected
