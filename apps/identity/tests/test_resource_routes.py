import unittest

from identity import IdentityHandler


class IdentityResourceRouteTests(unittest.TestCase):
    def setUp(self):
        self.previous_items = IdentityHandler.store.items
        self.previous_events = IdentityHandler.store.events
        self.previous_data = IdentityHandler.store.data
        self.previous_idempotency = IdentityHandler.store.idempotency
        IdentityHandler.store.items = {
            "account-1": {
                "id": "account-1",
                "email": "operator@example.test",
                "callsigns": [
                    {
                        "id": "callsign-1",
                        "value": "EA7TEST",
                        "status": "VERIFIED",
                    }
                ],
                "primaryCallsignId": None,
                "updatedAt": "initial",
            }
        }
        IdentityHandler.store.events = []
        IdentityHandler.store.data = {}
        IdentityHandler.store.idempotency = {}

    def tearDown(self):
        IdentityHandler.store.items = self.previous_items
        IdentityHandler.store.events = self.previous_events
        IdentityHandler.store.data = self.previous_data
        IdentityHandler.store.idempotency = self.previous_idempotency

    def test_phase1_aliases_use_existing_mutation_handlers(self):
        self.assertIs(
            IdentityHandler.routes[
                ("PATCH", "/v1/identity/accounts/{accountId}")
            ],
            IdentityHandler.update_admin_account,
        )
        self.assertIs(
            IdentityHandler.routes[("POST", "/v1/identity/roles")],
            IdentityHandler.create_admin_role,
        )
        self.assertIs(
            IdentityHandler.routes[("PATCH", "/v1/identity/roles/{roleCode}")],
            IdentityHandler.update_admin_role,
        )
        self.assertIs(
            IdentityHandler.routes[
                ("PUT", "/v1/identity/accounts/{accountId}/role-assignments")
            ],
            IdentityHandler.update_admin_account,
        )
        self.assertIs(
            IdentityHandler.routes[
                ("PUT", "/v1/identity/accounts/{accountId}/primary-callsign")
            ],
            IdentityHandler.set_primary,
        )

    def test_removed_legacy_mutations_are_not_registered_or_deprecated(self):
        removed_routes = {
            ("POST", "/v1/identity/admin/accounts/{accountId}/update"),
            ("POST", "/v1/identity/accounts/{accountId}/roles"),
        }
        self.assertTrue(removed_routes.isdisjoint(IdentityHandler.routes))
        self.assertEqual(IdentityHandler.deprecated_routes, set())

    def test_primary_callsign_put_is_idempotent_with_a_key(self):
        request = {
            "accountId": "account-1",
            "_body": {"callsignId": "callsign-1"},
            "Idempotency-Key": "primary-1",
        }
        first = IdentityHandler.set_primary(None, request)
        event_count = len(IdentityHandler.store.events)
        second = IdentityHandler.set_primary(None, request)
        self.assertEqual(first, second)
        self.assertEqual(len(IdentityHandler.store.events), event_count)


if __name__ == "__main__":
    unittest.main()
