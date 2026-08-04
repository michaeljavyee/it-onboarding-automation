"""Okta API client.

Two implementations behind one interface:

  OktaClient      — talks to a real Okta tenant over HTTPS.
  DemoOktaClient  — reads a JSON fixture and simulates writes in memory.

Everything in this repo is written against the interface, so `--demo` exercises
exactly the same code paths as a live run. That matters: a demo mode that takes
a different branch through the program proves nothing about the real branch.

The HTTP layer is carried over from my earlier project, okta-nhi-audit-tool.
The differences here are the write methods (suspend, revoke, unassign), which
that project deliberately did not have — it was read-only by design.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Protocol

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"


class OktaError(RuntimeError):
    """Raised when Okta returns something we can't proceed from."""


class OktaInterface(Protocol):
    """The surface offboard.py depends on. Both clients implement it."""

    def get_user(self, login: str) -> dict[str, Any]: ...
    def list_groups(self, user_id: str) -> list[dict[str, Any]]: ...
    def list_sessions(self, user_id: str) -> list[dict[str, Any]]: ...
    def list_oauth_grants(self, user_id: str) -> list[dict[str, Any]]: ...
    def list_app_assignments(self, user_id: str) -> list[dict[str, Any]]: ...
    def list_api_tokens_created_by(self, user_id: str) -> list[dict[str, Any]]: ...
    def suspend_user(self, user_id: str) -> None: ...
    def clear_sessions(self, user_id: str) -> None: ...
    def revoke_oauth_grants(self, user_id: str) -> None: ...
    def remove_from_group(self, user_id: str, group_id: str) -> None: ...


# --------------------------------------------------------------------------
# Real client
# --------------------------------------------------------------------------

class OktaClient:
    """Live Okta client. Requires OKTA_ORG_URL and OKTA_API_TOKEN."""

    def __init__(self, org_url: str | None = None, api_token: str | None = None):
        self.org_url = (org_url or os.environ.get("OKTA_ORG_URL", "")).rstrip("/")
        self.api_token = api_token or os.environ.get("OKTA_API_TOKEN", "")
        if not self.org_url or not self.api_token:
            raise OktaError(
                "OKTA_ORG_URL and OKTA_API_TOKEN must be set. "
                "Copy .env.example to .env, or run with --demo."
            )
        # Imported lazily so that --demo works without requests installed.
        import requests

        self._session = requests.Session()
        self._session.headers.update(
            {
                "Authorization": f"SSWS {self.api_token}",
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
        )

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        url = f"{self.org_url}{path}"
        response = self._session.request(method, url, timeout=30, **kwargs)
        if response.status_code == 429:
            raise OktaError("Rate limited by Okta. Wait and retry.")
        if not response.ok:
            raise OktaError(f"{method} {path} -> {response.status_code}: {response.text[:300]}")
        if response.status_code == 204 or not response.content:
            return None
        return response.json()

    def _paginate(self, path: str) -> list[dict[str, Any]]:
        """Okta pages via a Link header. Collect every page."""
        results: list[dict[str, Any]] = []
        url = f"{self.org_url}{path}"
        while url:
            response = self._session.get(url, timeout=30)
            if not response.ok:
                raise OktaError(f"GET {url} -> {response.status_code}")
            results.extend(response.json())
            url = response.links.get("next", {}).get("url", "")
        return results

    # --- reads -----------------------------------------------------------

    def get_user(self, login: str) -> dict[str, Any]:
        user = self._request("GET", f"/api/v1/users/{login}")
        user["admin_roles"] = [
            role["type"] for role in (self._request("GET", f"/api/v1/users/{user['id']}/roles") or [])
        ]
        return user

    def list_groups(self, user_id: str) -> list[dict[str, Any]]:
        return self._paginate(f"/api/v1/users/{user_id}/groups")

    def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        # Okta exposes no "list sessions for user" endpoint. The closest signal
        # is the system log. Documented honestly rather than faked.
        return self._paginate(
            f"/api/v1/logs?filter=actor.id+eq+%22{user_id}%22+and+"
            "eventType+eq+%22user.session.start%22"
        )

    def list_oauth_grants(self, user_id: str) -> list[dict[str, Any]]:
        return self._paginate(f"/api/v1/users/{user_id}/grants")

    def list_app_assignments(self, user_id: str) -> list[dict[str, Any]]:
        return self._paginate(f"/api/v1/users/{user_id}/appLinks")

    def list_api_tokens_created_by(self, user_id: str) -> list[dict[str, Any]]:
        tokens = self._paginate("/api/v1/api-tokens")
        return [t for t in tokens if t.get("userId") == user_id]

    # --- writes ----------------------------------------------------------

    def suspend_user(self, user_id: str) -> None:
        self._request("POST", f"/api/v1/users/{user_id}/lifecycle/suspend")

    def clear_sessions(self, user_id: str) -> None:
        self._request("DELETE", f"/api/v1/users/{user_id}/sessions?oauthTokens=true")

    def revoke_oauth_grants(self, user_id: str) -> None:
        self._request("DELETE", f"/api/v1/users/{user_id}/grants")

    def remove_from_group(self, user_id: str, group_id: str) -> None:
        self._request("DELETE", f"/api/v1/groups/{group_id}/users/{user_id}")


# --------------------------------------------------------------------------
# Demo client
# --------------------------------------------------------------------------

class DemoOktaClient:
    """Fixture-backed client. No network, no credentials, no side effects.

    Writes mutate the in-memory copy of the fixture, so the verification pass
    genuinely re-reads changed state rather than replaying a canned answer.
    The one exception is the API token, which stays ACTIVE — because in real
    Okta it does. That is the point the report is making.
    """

    def __init__(self, fixture: str = "leaver_jdoe.json"):
        path = Path(fixture)
        if not path.exists():
            path = FIXTURES_DIR / fixture
        if not path.exists():
            raise OktaError(f"Fixture not found: {fixture}")
        self.state: dict[str, Any] = json.loads(path.read_text())

    # --- reads -----------------------------------------------------------

    def get_user(self, login: str) -> dict[str, Any]:
        user = self.state["user"]
        if login not in (user["login"], user["id"]):
            raise OktaError(
                f"Fixture holds {user['login']}, not {login}. "
                "Pass --fixture to select a different one."
            )
        return user

    def list_groups(self, user_id: str) -> list[dict[str, Any]]:
        return list(self.state["groups"])

    def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        return list(self.state["sessions"])

    def list_oauth_grants(self, user_id: str) -> list[dict[str, Any]]:
        return list(self.state["oauth_grants"])

    def list_app_assignments(self, user_id: str) -> list[dict[str, Any]]:
        return list(self.state["app_assignments"])

    def list_api_tokens_created_by(self, user_id: str) -> list[dict[str, Any]]:
        return [t for t in self.state["api_tokens"] if t.get("createdBy") == user_id]

    # --- writes ----------------------------------------------------------

    def suspend_user(self, user_id: str) -> None:
        self.state["user"]["status"] = "SUSPENDED"

    def clear_sessions(self, user_id: str) -> None:
        self.state["sessions"] = []

    def revoke_oauth_grants(self, user_id: str) -> None:
        self.state["oauth_grants"] = []

    def remove_from_group(self, user_id: str, group_id: str) -> None:
        self.state["groups"] = [g for g in self.state["groups"] if g["id"] != group_id]
        if not self.state["groups"]:
            # Once the last group is gone, SCIM-managed apps deprovision
            # downstream. Apps that are not SCIM-managed do not — they stay
            # assigned, and nothing in Okta will tell you so unless you look.
            # That gap is exactly what the verification stage is for.
            self.state["app_assignments"] = [
                a for a in self.state["app_assignments"] if not a.get("scim", False)
            ]


def build_client(demo: bool, fixture: str = "leaver_jdoe.json") -> OktaInterface:
    """Single place that decides which client the tools get."""
    return DemoOktaClient(fixture) if demo else OktaClient()
