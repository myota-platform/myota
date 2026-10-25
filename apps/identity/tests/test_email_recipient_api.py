import json
import os
import threading
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import unittest
from unittest.mock import patch

from common import verify_token
from identity import IdentityHandler, seed


class EmailRecipientApiTests(unittest.TestCase):
    def setUp(self):
        self.previous_items = IdentityHandler.store.items
        self.previous_events = IdentityHandler.store.events
        self.previous_data = IdentityHandler.store.data
        self.previous_idempotency = IdentityHandler.store.idempotency
        IdentityHandler.store.items = {}
        IdentityHandler.store.events = []
        IdentityHandler.store.data = {}
        IdentityHandler.store.idempotency = {}
        seed()
        self.account_id = "566b8475-bda2-4a2d-8ab8-d7a9a93c0041"
        IdentityHandler.store.items[self.account_id] = {
            "id": self.account_id,
            "displayName": "Private Person",
            "email": "private@example.test",
            "status": "ACTIVE",
            "websiteUrl": "https://private.example.test",
        }
        self.client_secret = "e" * 64

    def tearDown(self):
        IdentityHandler.store.items = self.previous_items
        IdentityHandler.store.events = self.previous_events
        IdentityHandler.store.data = self.previous_data
        IdentityHandler.store.idempotency = self.previous_idempotency

    def token(self):
        params = {
            "_http": "1",
            "_body": {
                "service": "email-service",
                "clientSecret": self.client_secret,
            },
        }
        with patch.dict(
            os.environ,
            {"MYOTA_EMAIL_SERVICE_CLIENT_SECRET": self.client_secret},
        ):
            response = IdentityHandler.issue_service_token(None, params)
        return response["accessToken"]

    def test_email_client_secret_mints_only_fixed_short_lived_scope(self):
        token = self.token()
        claims = verify_token(token, None)
        self.assertEqual(claims["sub"], "service:email-service")
        self.assertEqual(claims["aud"], "myota-identity")
        self.assertEqual(claims["scp"], ["identity.email.resolve"])
        self.assertEqual(claims["exp"] - claims["iat"], 300)
        self.assertNotIn(self.client_secret, str(IdentityHandler.store.events))

    def test_email_client_rejects_bad_secret_and_caller_selected_scopes(self):
        params = {
            "_http": "1",
            "_body": {
                "service": "email-service",
                "clientSecret": "wrong",
            },
        }
        with (
            patch.dict(
                os.environ,
                {"MYOTA_EMAIL_SERVICE_CLIENT_SECRET": self.client_secret},
            ),
            self.assertRaises(PermissionError),
        ):
            IdentityHandler.issue_service_token(None, params)

        params["_body"]["clientSecret"] = self.client_secret
        params["_body"]["scopes"] = ["*"]
        with (
            patch.dict(
                os.environ,
                {"MYOTA_EMAIL_SERVICE_CLIENT_SECRET": self.client_secret},
            ),
            self.assertRaises(ValueError),
        ):
            IdentityHandler.issue_service_token(None, params)

    def test_human_service_issuer_cannot_mint_reserved_email_scope(self):
        root = IdentityHandler.store.items[
            "00000000-0000-4000-8000-000000000001"
        ]
        auth = (
            "Bearer " + IdentityHandler._mint_tokens(root, {})["accessToken"]
        )
        params = {
            "_http": "1",
            "Authorization": auth,
            "_body": {
                "service": "other-service",
                "scopes": ["identity.email.resolve"],
            },
        }
        with self.assertRaises(PermissionError):
            IdentityHandler.issue_service_token(None, params)

    def test_resolver_returns_only_address_for_matching_service_token(self):
        params = {
            "_http": "1",
            "Authorization": "Bearer " + self.token(),
            "accountId": self.account_id,
        }
        result = IdentityHandler.resolve_email_recipient(None, params)
        self.assertEqual(
            result, {"deliverableAddress": "private@example.test"}
        )

    def test_resolver_rejects_wrong_service_and_human_tokens(self):
        root = IdentityHandler.store.items[
            "00000000-0000-4000-8000-000000000001"
        ]
        human = IdentityHandler._mint_tokens(root, {})["accessToken"]
        params = {
            "_http": "1",
            "Authorization": "Bearer " + human,
            "accountId": self.account_id,
        }
        with self.assertRaises(PermissionError):
            IdentityHandler.resolve_email_recipient(None, params)

        claims = {
            "sub": "service:another-service",
            "aud": "myota-identity",
            "scp": ["identity.email.resolve"],
            "iat": 1,
            "exp": 2147483647,
            "jti": "another-service-token",
            "tokenType": "service",
        }
        from common import sign_token

        params["Authorization"] = "Bearer " + sign_token(claims, "service")
        with self.assertRaises(PermissionError):
            IdentityHandler.resolve_email_recipient(None, params)

    def test_http_unavailable_responses_are_404_without_recipient_data(self):
        token = self.token()
        server = ThreadingHTTPServer(("127.0.0.1", 0), IdentityHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            responses = []
            for status in ("DEACTIVATED", "PENDING_SETUP", None):
                if status is None:
                    IdentityHandler.store.items.pop(self.account_id, None)
                else:
                    IdentityHandler.store.items[self.account_id]["status"] = (
                        status
                    )
                connection = HTTPConnection(
                    "127.0.0.1", server.server_port, timeout=5
                )
                try:
                    connection.request(
                        "GET",
                        f"/v1/identity/internal/email-recipients/{self.account_id}",
                        headers={"Authorization": "Bearer " + token},
                    )
                    response = connection.getresponse()
                    self.assertEqual(response.status, 404)
                    self.assertEqual(
                        response.getheader("Cache-Control"),
                        "private, no-store",
                    )
                    body = json.loads(response.read())
                    self.assertNotIn("private@example.test", str(body))
                    responses.append(
                        {
                            k: v
                            for k, v in body.items()
                            if k not in {"requestId", "correlationId"}
                        }
                    )
                finally:
                    connection.close()
            self.assertEqual(responses[0], responses[1])
            self.assertEqual(responses[1], responses[2])
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_missing_deactivated_or_unaddressable_accounts_are_indistinguishable(
        self,
    ):
        token = self.token()
        for account in (
            None,
            {
                "id": self.account_id,
                "status": "DEACTIVATED",
                "email": "x@y.test",
            },
            {
                "id": self.account_id,
                "status": "PENDING_SETUP",
                "email": "x@y.test",
            },
            {"id": self.account_id, "status": "ACTIVE", "email": None},
        ):
            with self.subTest(account=account):
                if account is None:
                    IdentityHandler.store.items.pop(self.account_id, None)
                else:
                    IdentityHandler.store.items[self.account_id] = account
                params = {
                    "_http": "1",
                    "Authorization": "Bearer " + token,
                    "accountId": self.account_id,
                }
                with self.assertRaisesRegex(
                    KeyError, "recipient is unavailable"
                ):
                    IdentityHandler.resolve_email_recipient(None, params)


if __name__ == "__main__":
    unittest.main()
