import pytest

from sds import identity


def test_verify_identity_returns_false_when_not_configured():
    assert identity.verify_identity("", "runner") is False
    assert identity.verify_identity("fingerprint", "") is False


def test_verify_identity_accepts_case_insensitive_user_match(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("USER", "Runner")
    assert identity.verify_identity("fingerprint", " runner ") is True


def test_verify_identity_rejects_different_user(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("USER", "alice")
    assert identity.verify_identity("fingerprint", "bob") is False
