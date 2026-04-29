"""Tests for Compliance Agent."""


def test_import():
    from compliance_agent import __version__

    assert __version__ == "0.1.0"
