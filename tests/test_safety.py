"""Tests for the guardrails.

These are the tests that matter most in this repo. A bug in report formatting
is embarrassing; a bug in the admin check locks someone out of the tenant.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import safety  # noqa: E402


def test_refuses_admin_account_without_override():
    user = {"login": "admin@example.com", "admin_roles": ["SUPER_ADMIN"]}
    with pytest.raises(safety.SafetyViolation) as exc:
        safety.check_not_admin(user, override=False)
    assert "SUPER_ADMIN" in str(exc.value)


def test_allows_admin_account_with_explicit_override():
    user = {"login": "admin@example.com", "admin_roles": ["SUPER_ADMIN"]}
    safety.check_not_admin(user, override=True)  # must not raise


def test_allows_normal_account():
    safety.check_not_admin({"login": "jdoe@example.com", "admin_roles": []}, override=False)


def test_missing_admin_roles_key_is_treated_as_no_roles():
    safety.check_not_admin({"login": "jdoe@example.com"}, override=False)


def test_confirmation_rejects_mismatched_input(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "wrong@example.com")
    with pytest.raises(safety.SafetyViolation):
        safety.confirm_apply("jdoe@example.com")


def test_confirmation_accepts_exact_login(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda _: "jdoe@example.com")
    safety.confirm_apply("jdoe@example.com")


def test_audit_log_records_dry_run_intentions_too():
    log = safety.AuditLog(target="jdoe@example.com", mode="dry-run", enabled=False)
    log.record("write", "Okta account suspended", executed=False)
    assert len(log.entries) == 1
    assert log.entries[0]["executed"] is False
    assert log.entries[0]["target"] == "jdoe@example.com"
