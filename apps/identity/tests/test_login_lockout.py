import unittest

from identity import IdentityHandler, seed


class IdentityLoginLockoutTests(unittest.TestCase):
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

    def tearDown(self):
        IdentityHandler.store.items = self.previous_items
        IdentityHandler.store.events = self.previous_events
        IdentityHandler.store.data = self.previous_data
        IdentityHandler.store.idempotency = self.previous_idempotency

    def _login(self, email, password):
        return IdentityHandler.login(
            None,
            {
                "_body": {"email": email, "password": password},
                "Remote-Addr": "192.0.2.10",
            },
        )

    def test_global_operator_bypasses_general_login_attempt_throttle(self):
        for _ in range(12):
            result = self._login(
                "demo@example.test", "DemoOperator!ChangeMe2026"
            )
            self.assertTrue(result["accessToken"])

        self.assertNotIn(
            "login:demo@example.test:192.0.2.10",
            IdentityHandler._bucket("rateLimits"),
        )

    def test_other_accounts_remain_subject_to_general_login_attempt_throttle(
        self,
    ):
        account = {
            "id": "account-standard",
            "displayName": "Standard Operator",
            "email": "standard@example.test",
            "participationType": "OPERATOR",
            "status": "ACTIVE",
            "callsigns": [],
            "primaryCallsignId": None,
        }
        IdentityHandler.store.items[account["id"]] = account
        IdentityHandler._set_password(
            account["id"], "StandardOperatorPassword!2026"
        )

        for _ in range(8):
            self._login(
                "standard@example.test", "StandardOperatorPassword!2026"
            )
        with self.assertRaisesRegex(
            PermissionError, "too many authentication attempts"
        ):
            self._login(
                "standard@example.test", "StandardOperatorPassword!2026"
            )

    def test_global_operator_still_locks_after_repeated_bad_passwords(self):
        for _ in range(5):
            with self.assertRaisesRegex(ValueError, "invalid credentials"):
                self._login("demo@example.test", "incorrect password")

        with self.assertRaisesRegex(
            PermissionError, "account temporarily locked"
        ):
            self._login("demo@example.test", "DemoOperator!ChangeMe2026")


if __name__ == "__main__":
    unittest.main()
