"""Guardrails.

This is the only project in my portfolio that writes to Okta, so the rails come
before the features. Four of them:

  1. Dry-run by default.  Nothing writes unless --apply is passed.
  2. Admin refusal.       Accounts holding an admin role are refused outright
                          unless the operator explicitly acknowledges it.
  3. Typed confirmation.  --apply prompts for the user's login, typed in full.
  4. Append-only log.     Every intended and executed action is recorded.

Deliberately isolated in its own module with its own tests, so "did the safety
check run?" is a question with a provable answer.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

AUDIT_DIR = Path(__file__).resolve().parent.parent / "audit-log"


class SafetyViolation(Exception):
    """Raised when a guardrail refuses an action. Never caught internally."""


def check_not_admin(user: dict[str, Any], override: bool) -> None:
    """Refuse to operate on an account holding any admin role.

    Offboarding an admin is a legitimate thing to need to do — but it should
    require someone to have read the account first, not be something you
    stumble into from a script argument typo.
    """
    roles = user.get("admin_roles") or []
    if roles and not override:
        raise SafetyViolation(
            f"Refusing to modify {user['login']}: account holds "
            f"{', '.join(roles)}.\n"
            "Re-run with --i-know-this-is-an-admin if this is intentional, "
            "and confirm the break-glass account still works first."
        )


def confirm_apply(login: str, non_interactive: bool = False) -> None:
    """Require the operator to type the target login before any write."""
    if non_interactive:
        return
    print(f"\nAbout to make irreversible changes to {login}.")
    typed = input(f"Type the full login to continue ({login}): ").strip()
    if typed != login:
        raise SafetyViolation("Confirmation did not match. Nothing was changed.")


def operator() -> str:
    return os.environ.get("OPERATOR_EMAIL", "unknown-operator")


class AuditLog:
    """Append-only JSONL record of every action, dry-run included.

    Dry-run entries are logged too. "We ran it in dry-run and it said it would
    delete the wrong thing" is only a defensible statement if there is a record.
    """

    def __init__(self, target: str, mode: str, enabled: bool = True):
        self.target = target
        self.mode = mode
        self.enabled = enabled
        self.entries: list[dict[str, Any]] = []
        self.path: Path | None = None
        if enabled:
            AUDIT_DIR.mkdir(exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d")
            self.path = AUDIT_DIR / f"{stamp}.jsonl"

    def record(self, action: str, detail: str, executed: bool) -> None:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "operator": operator(),
            "target": self.target,
            "mode": self.mode,
            "action": action,
            "detail": detail,
            "executed": executed,
        }
        self.entries.append(entry)
        if self.enabled and self.path is not None:
            with self.path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry) + "\n")


def die(message: str) -> None:
    """Exit non-zero with a message on stderr. Used for guardrail failures."""
    print(f"\nREFUSED: {message}\n", file=sys.stderr)
    raise SystemExit(2)
