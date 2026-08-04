"""Tests for the offboarding sequence and, mainly, its verification stage."""

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(SRC))

import offboard  # noqa: E402
from okta_client import DemoOktaClient  # noqa: E402


def run_demo(fixture="leaver_jdoe.json"):
    return offboard.main(["--demo", "--fixture", fixture])


def test_demo_exits_nonzero_when_manual_items_remain():
    assert run_demo() == 1


def test_demo_admin_is_refused_without_override():
    with pytest.raises(SystemExit) as exc:
        run_demo("leaver_admin.json")
    assert exc.value.code == 2


def test_demo_admin_runs_with_override():
    assert offboard.main(
        ["--demo", "--fixture", "leaver_admin.json", "--i-know-this-is-an-admin"]
    ) == 0


def test_dry_run_makes_no_changes():
    """The whole point of dry-run: state must be identical afterwards."""
    client = DemoOktaClient("leaver_jdoe.json")
    user = client.get_user("jdoe@example.com")
    import safety

    audit = safety.AuditLog(target=user["login"], mode="dry-run", enabled=False)
    run = offboard.OffboardRun(client, user, writes_enabled=False, audit=audit)
    run.run_actions()

    assert client.state["user"]["status"] == "ACTIVE"
    assert len(client.state["sessions"]) == 3
    assert len(client.state["groups"]) == 7


def test_verification_catches_the_surviving_api_token():
    """Suspension does not kill an API token the user created. Prove we say so."""
    client = DemoOktaClient("leaver_jdoe.json")
    user = client.get_user("jdoe@example.com")
    import safety

    audit = safety.AuditLog(target=user["login"], mode="demo", enabled=False)
    run = offboard.OffboardRun(client, user, writes_enabled=True, audit=audit, is_demo=True)
    run.run_actions()
    run.verify()

    critical = [text for severity, text in run.findings if severity == "crit"]
    assert any("jenkins-integration" in text for text in critical)


def test_verification_catches_non_scim_app_left_assigned():
    client = DemoOktaClient("leaver_jdoe.json")
    user = client.get_user("jdoe@example.com")
    import safety

    audit = safety.AuditLog(target=user["login"], mode="demo", enabled=False)
    run = offboard.OffboardRun(client, user, writes_enabled=True, audit=audit, is_demo=True)
    run.run_actions()
    run.verify()

    warnings = [text for severity, text in run.findings if severity == "warn"]
    assert any("Zoom" in text for text in warnings)
    # And Google Workspace, which *is* SCIM-managed, must NOT still be listed.
    assert not any("Google Workspace" in text for text in warnings)


def test_report_contains_the_headline_sections():
    client = DemoOktaClient("leaver_jdoe.json")
    user = client.get_user("jdoe@example.com")
    import safety

    audit = safety.AuditLog(target=user["login"], mode="demo", enabled=False)
    run = offboard.OffboardRun(client, user, writes_enabled=True, audit=audit, is_demo=True)
    run.run_actions()
    run.verify()
    report = run.render("2026-08-15 14:32", "michael@example.com")

    assert "OFFBOARDING REPORT — jdoe@example.com" in report
    assert "VERIFICATION (independent re-query)" in report
    assert "Offboarding is NOT complete." in report
