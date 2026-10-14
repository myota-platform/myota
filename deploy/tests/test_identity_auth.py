from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "services"))

from identity import IdentityHandler, seed
from common import verify_token


class IdentityAuthTests(unittest.TestCase):
    def setUp(self) -> None:
        IdentityHandler.store.items.clear()
        IdentityHandler.store.events.clear()
        IdentityHandler.store.data.clear()
        IdentityHandler.store.idempotency.clear()
        seed()

    def call(self, fn, body=None, **params):
        return fn(None, {"_body": body or {}, **params})

    def create_account(self, body):
        account_id = "test-" + body["email"]
        account = {
            "id": account_id,
            "displayName": body["displayName"],
            "email": body["email"],
            "participationType": body["participationType"],
            "status": "ACTIVE",
            "callsigns": [],
            "primaryCallsignId": None,
        }
        IdentityHandler.store.items[account_id] = account
        IdentityHandler._set_password(account_id, body["password"])
        if body.get("callsign"):
            IdentityHandler._add_callsign(
                account, body["callsign"], "UNVERIFIED", "self-asserted"
            )
        return account

    def test_login_refresh_logout_and_revocation(self) -> None:
        account = self.create_account(
            {
                "displayName": "Auth Operator",
                "email": "auth@example.test",
                "password": "A secure password 2026!",
                "participationType": "OPERATOR",
                "callsign": "N0AUTH",
            }
        )
        self.assertEqual(
            account["primaryCallsignId"], account["callsigns"][0]["id"]
        )
        logged_in = self.call(
            IdentityHandler.login,
            {
                "email": "auth@example.test",
                "password": "A secure password 2026!",
                "Remote-Addr": "127.0.0.1",
            },
        )
        self.assertEqual(
            verify_token(logged_in["accessToken"], "access")["sub"],
            account["id"],
        )
        refreshed = self.call(
            IdentityHandler.refresh,
            {"refreshToken": logged_in["refreshToken"]},
        )
        self.assertNotEqual(
            refreshed["refreshToken"], logged_in["refreshToken"]
        )
        self.call(
            IdentityHandler.logout, {"refreshToken": refreshed["refreshToken"]}
        )
        with self.assertRaises(PermissionError):
            IdentityHandler.refresh(
                None, {"_body": {"refreshToken": refreshed["refreshToken"]}}
            )

    def test_recovery_and_callsign_evidence_lifecycle(self) -> None:
        account = self.create_account(
            {
                "displayName": "Evidence Operator",
                "email": "evidence@example.test",
                "password": "Another secure password!",
                "participationType": "OPERATOR",
                "callsign": "EA7EVID",
            }
        )
        token = self.call(
            IdentityHandler.recovery_request,
            {"email": "evidence@example.test"},
        )["devResetToken"]
        self.call(
            IdentityHandler.recovery_reset,
            {"token": token, "newPassword": "Replacement password 2026!"},
        )
        callsign = account["callsigns"][0]
        evidence = self.call(
            IdentityHandler.add_evidence,
            {"evidenceType": "LICENSE", "source": "national-regulator"},
            accountId=account["id"],
            callsignId=callsign["id"],
        )
        self.assertEqual(evidence["status"], "PENDING")
        reviewer = {
            "Authorization": "Bearer "
            + IdentityHandler._mint_tokens(
                IdentityHandler.store.items[
                    "00000000-0000-4000-8000-000000000001"
                ],
                {},
            )["accessToken"],
            "_http": "1",
            "_body": {"source": "review"},
            "accountId": account["id"],
            "callsignId": callsign["id"],
        }
        self.assertEqual(
            IdentityHandler.verify_callsign(None, reviewer)["status"],
            "VERIFIED",
        )

    def test_scoped_role_and_privacy_export(self) -> None:
        account = self.create_account(
            {
                "displayName": "Scoped Operator",
                "email": "scoped@example.test",
                "password": "Scoped secure password!",
                "participationType": "SWL",
            }
        )
        admin = IdentityHandler._mint_tokens(
            IdentityHandler.store.items[
                "00000000-0000-4000-8000-000000000001"
            ],
            {},
        )["accessToken"]
        role = self.call(
            IdentityHandler.assign_role,
            {
                "role": "GEO_APPROVER",
                "programmeSlug": "regional-ota",
                "scopes": ["geodata.review"],
            },
            accountId=account["id"],
            Authorization="Bearer " + admin,
            _http="1",
        )
        self.assertEqual(role["programmeSlug"], "regional-ota")
        export = self.call(
            IdentityHandler.export_account,
            {},
            accountId=account["id"],
            Authorization="Bearer "
            + IdentityHandler._mint_tokens(account, {})["accessToken"],
            _http="1",
        )
        self.assertEqual(export["account"]["id"], account["id"])
        self.call(
            IdentityHandler.deactivate_account,
            {"anonymize": True},
            accountId=account["id"],
            Authorization="Bearer "
            + IdentityHandler._mint_tokens(account, {})["accessToken"],
            _http="1",
        )
        self.assertEqual(
            IdentityHandler.store.items[account["id"]]["status"], "DEACTIVATED"
        )


if __name__ == "__main__":
    unittest.main()
