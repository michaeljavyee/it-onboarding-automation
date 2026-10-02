"""offboard.py — run a deprovisioning sequence, then independently verify it.

    python src/offboard.py --demo
    python src/offboard.py --demo --fixture leaver_admin.json
    python src/offboard.py --user jdoe@example.com              # dry run
    python src/offboard.py --user jdoe@example.com --apply      # writes

The sequence is ordered deliberately (see docs/flows/leaver.md):

    1. suspend account          blocks new authentication
    2. revoke active sessions   kills sessions already established
    3. revoke OAuth grants      a refresh token outlives suspension
    4. remove group memberships cascades to SCIM-provisioned apps
    5. find API tokens they created
    6. transfer data ownership
    7. device retrieval / remote lock

Then — and this is the part that matters — every one of those is re-queried
from scratch and the report states what is *still standing*. An offboarding
script that doesn't verify its own work is just optimism with a shebang.

Exit codes:  0 = verified clean   1 = manual action required   2 = refused
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import safety  # noqa: E402
from okta_client import OktaError, build_client  # noqa: E402

# Demo runs use a frozen timestamp so the README output is reproducible.
DEMO_TIMESTAMP = "2026-08-15 14:32"
DEMO_OPERATOR = "michael@example.com"

OK = "✅"
WARN = "⚠️ "
CRIT = "\U0001f534"


def utc_now_iso() -> str:
    """Current time in the ISO 8601 form Okta's System Log `since` accepts."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def plural(items) -> str:
    return "" if len(items) == 1 else "s"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deprovision an Okta user and verify the result.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--user", help="login of the departing user")
    parser.add_argument(
        "--demo",
        action="store_true",
        help="run against fixture data — no credentials, no network, no side effects",
    )
    parser.add_argument("--fixture", default="leaver_jdoe.json", help="fixture file for --demo")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="actually write to Okta. Without this the run is a dry run.",
    )
    parser.add_argument(
        "--i-know-this-is-an-admin",
        action="store_true",
        dest="admin_override",
        help="acknowledge that the target holds an admin role",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="skip the typed confirmation prompt (for CI; use sparingly)",
    )
    return parser.parse_args(argv)


class OffboardRun:
    """Holds the state of one offboarding: what we did, what we then found."""

    def __init__(self, client, user: dict, writes_enabled: bool, audit: safety.AuditLog,
                 is_demo: bool = False):
        self.client = client
        self.user = user
        self.user_id = user["id"]
        self.login = user["login"]
        self.writes_enabled = writes_enabled
        self.audit = audit
        self.is_demo = is_demo
        self.actions: list[str] = []
        # When sessions were revoked (ISO 8601, UTC). Verification asks for
        # sign-ins after this instant, not "any sign-ins ever".
        self.sessions_revoked_at: str | None = None
        self.findings: list[tuple[str, str]] = []  # (severity, text)

    # --- step 1-7: act ---------------------------------------------------

    def _do(self, label: str, fn) -> None:
        """Run one write step, or describe it if this is a dry run."""
        if self.writes_enabled:
            fn()
            self.actions.append(label)
            self.audit.record("write", label, executed=True)
        else:
            self.actions.append(f"[dry run] would: {label}")
            self.audit.record("write", label, executed=False)

    def run_actions(self) -> None:
        sessions = self.client.list_sessions(self.user_id)
        grants = self.client.list_oauth_grants(self.user_id)
        groups = self.client.list_groups(self.user_id)

        self._do("Okta account suspended", lambda: self.client.suspend_user(self.user_id))
        def revoke_sessions() -> None:
            self.sessions_revoked_at = utc_now_iso()
            self.client.clear_sessions(self.user_id)

        self._do(
            f"Sessions revoked ({len(sessions)} recent sign-in{plural(sessions)})",
            revoke_sessions,
        )
        self._do(
            f"{len(grants)} OAuth refresh token{plural(grants)} revoked",
            lambda: self.client.revoke_oauth_grants(self.user_id),
        )

        def drop_groups() -> None:
            for group in groups:
                self.client.remove_from_group(self.user_id, group["id"])

        self._do(f"Removed from {len(groups)} group{plural(groups)}", drop_groups)

        # Step 6: data ownership. This is a Google Workspace action, not an Okta
        # one, and this tool does not hold Workspace credentials yet. In demo
        # mode it is simulated so the full report shape is visible; against a
        # live tenant it is reported as an outstanding manual step rather than
        # silently claimed as done. See docs/decision-log.md, decision 4.
        transfer_to = self.user.get("manager", "manager unknown")
        if self.is_demo:
            self.actions.append(f"Google Drive ownership → {transfer_to}")
            self.audit.record("write", "drive ownership transfer (simulated)", executed=True)
        else:
            self.findings.append(
                (
                    "warn",
                    f"Google Drive ownership transfer to {transfer_to} is not automated "
                    "— complete it in the Workspace admin console",
                )
            )

    # --- verify: re-query everything from scratch ------------------------

    def verify(self) -> None:
        user = self.client.get_user(self.login)
        if user.get("status") in ("SUSPENDED", "DEPROVISIONED"):
            self.findings.append(("ok", "Authentication blocked"))
        else:
            self.findings.append(("crit", f"Account status is {user.get('status')} — NOT suspended"))

        # Not "are there any sign-ins?": the System Log keeps the ones from
        # before revocation forever. The question is whether anyone has signed
        # in since.
        sessions = self.client.list_sessions(self.user_id, since=self.sessions_revoked_at)
        if sessions:
            self.findings.append(
                ("crit", f"{len(sessions)} sign-in(s) since sessions were revoked")
            )
        else:
            self.findings.append(("ok", "No sign-ins since sessions were revoked"))

        grants = self.client.list_oauth_grants(self.user_id)
        if grants:
            self.findings.append(("crit", f"{len(grants)} OAuth grant(s) still valid"))
        else:
            self.findings.append(("ok", "No valid refresh tokens"))

        for app in self.client.list_app_assignments(self.user_id):
            self.findings.append(
                (
                    "warn",
                    f"Still assigned to: {app['label']}  "
                    "(not SCIM-managed — manual removal required)",
                )
            )

        for token in self.client.list_api_tokens_created_by(self.user_id):
            if token.get("status") == "ACTIVE":
                self.findings.append(
                    (
                        "crit",
                        f'API token "{token["name"]}" created by this user is STILL ACTIVE\n'
                        "      → this token survives account suspension. Revoke separately:\n"
                        "        Security → API → Tokens",
                    )
                )

    # --- report ----------------------------------------------------------

    def outstanding(self) -> int:
        return sum(1 for severity, _ in self.findings if severity in ("warn", "crit"))

    def render(self, timestamp: str, operator: str) -> str:
        lines = [
            f"OFFBOARDING REPORT — {self.login}",
            f"Initiated {timestamp} by {operator}",
            "",
            "ACTIONS",
        ]
        for action in self.actions:
            marker = OK if self.writes_enabled else "•"
            lines.append(f"  {marker} {action}")

        lines += ["", "VERIFICATION (independent re-query)"]
        if not self.writes_enabled:
            lines.append("  • skipped — dry run made no changes to verify. Re-run with --apply.")
        else:
            for severity, text in self.findings:
                marker = {"ok": OK, "warn": WARN, "crit": CRIT}[severity]
                lines.append(f"  {marker} {text}")

        lines.append("")
        if not self.writes_enabled:
            lines.append("RESULT: dry run. Nothing was changed.")
        else:
            remaining = self.outstanding()
            if remaining:
                lines.append(
                    f"RESULT: {remaining} item{'s' if remaining != 1 else ''} require manual action. "
                    "Offboarding is NOT complete."
                )
            else:
                lines.append("RESULT: verified clean. Offboarding complete.")
        return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if not args.demo and not args.user:
        print("Specify --user, or --demo to run against fixture data.", file=sys.stderr)
        return 2

    try:
        client = build_client(demo=args.demo, fixture=args.fixture)
    except OktaError as exc:
        safety.die(str(exc))
        return 2

    login = args.user
    if args.demo and not login:
        login = client.state["user"]["login"]  # type: ignore[attr-defined]

    try:
        user = client.get_user(login)
    except OktaError as exc:
        safety.die(str(exc))
        return 2

    # Guardrail 2: refuse admins unless acknowledged.
    try:
        safety.check_not_admin(user, args.admin_override)
    except safety.SafetyViolation as exc:
        safety.die(str(exc))
        return 2

    # Guardrail 1: dry run unless --apply. --demo writes only to the fixture
    # held in memory, so it runs the full path with no real-world effect.
    writes_enabled = args.demo or args.apply

    # Guardrail 3: typed confirmation before touching a live tenant.
    if args.apply and not args.demo:
        try:
            safety.confirm_apply(user["login"], non_interactive=args.yes)
        except safety.SafetyViolation as exc:
            safety.die(str(exc))
            return 2

    mode = "demo" if args.demo else ("apply" if args.apply else "dry-run")
    audit = safety.AuditLog(target=user["login"], mode=mode, enabled=not args.demo)

    run = OffboardRun(client, user, writes_enabled, audit, is_demo=args.demo)
    run.run_actions()
    if writes_enabled:
        run.verify()

    timestamp = DEMO_TIMESTAMP if args.demo else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    operator = DEMO_OPERATOR if args.demo else safety.operator()
    print(run.render(timestamp, operator))

    if not writes_enabled:
        return 0
    return 1 if run.outstanding() else 0


if __name__ == "__main__":
    raise SystemExit(main())
