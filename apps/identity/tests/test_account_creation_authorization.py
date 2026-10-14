import unittest

from identity import IdentityHandler, seed


class IdentityAccountCreationAuthorizationTests(unittest.TestCase):
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
        self.root = IdentityHandler.store.items[
            "00000000-0000-4000-8000-000000000001"
        ]

    def tearDown(self):
        IdentityHandler.store.items = self.previous_items
        IdentityHandler.store.events = self.previous_events
        IdentityHandler.store.data = self.previous_data
        IdentityHandler.store.idempotency = self.previous_idempotency

    def token(self, account):
        return IdentityHandler._mint_tokens(account, {})["accessToken"]

    def request(self, body, account=None, **extra):
        params = {"_body": body, "_http": "1", **extra}
        if account:
            params["Authorization"] = "Bearer " + self.token(account)
        return IdentityHandler.create_account(None, params)

    def new_identity_admin(self):
        account_id = "identity-admin-test"
        account = {
            "id": account_id,
            "displayName": "Identity Admin",
            "email": "identity-admin@example.test",
            "participationType": "OPERATOR",
            "status": "ACTIVE",
            "callsigns": [],
            "primaryCallsignId": None,
        }
        IdentityHandler.store.items[account_id] = account
        role = {
            "id": "identity-admin-role-test",
            "accountId": account_id,
            "role": "IDENTITY_ADMIN",
            "programmeSlug": None,
            "jurisdiction": None,
            "entityType": None,
            "createdAt": "2026-01-01T00:00:00Z",
            "validTo": None,
        }
        IdentityHandler._bucket("roles")[role["id"]] = role
        return account

    def test_account_creation_requires_authenticated_identity_permission(self):
        body = {
            "displayName": "New Participant",
            "email": "new@example.test",
            "participationType": "OPERATOR",
        }
        with self.assertRaises(PermissionError):
            self.request(body)

        participant = {
            "id": "ordinary-user",
            "displayName": "Ordinary User",
            "email": "ordinary@example.test",
            "participationType": "SWL",
            "status": "ACTIVE",
            "callsigns": [],
            "primaryCallsignId": None,
        }
        IdentityHandler.store.items[participant["id"]] = participant
        with self.assertRaises(PermissionError):
            self.request(body, participant)

    def test_created_account_is_pending_setup_and_has_only_participant_role(
        self,
    ):
        result = self.request(
            {
                "displayName": "New Participant",
                "email": " New@Example.Test ",
                "participationType": "OPERATOR",
            },
            self.root,
            **{"Idempotency-Key": "create-participant-1"},
        )
        account_id = result["id"]
        self.assertEqual(result["email"], "new@example.test")
        self.assertEqual(result["status"], "PENDING_SETUP")
        self.assertEqual(
            [role["role"] for role in result["roles"]], ["PARTICIPANT"]
        )
        self.assertNotIn("password", result)
        self.assertEqual(
            next(
                event
                for event in IdentityHandler.store.events
                if event["eventType"] == "identity.account.created.v1"
            )["payload"]["actorId"],
            self.root["id"],
        )
        self.assertEqual(
            IdentityHandler._roles(account_id)[0]["role"], "PARTICIPANT"
        )
        self.assertEqual(
            next(iter(IdentityHandler._bucket("securityEvents").values()))[
                "payload"
            ]["actorId"],
            self.root["id"],
        )

    def test_create_is_idempotent_before_duplicate_email_validation(self):
        params = {
            "_body": {
                "displayName": "Idempotent Participant",
                "email": "retry@example.test",
                "participationType": "SWL",
            },
            "_http": "1",
            "Authorization": "Bearer " + self.token(self.root),
            "Idempotency-Key": "create-retry-1",
        }
        first = IdentityHandler.create_account(None, params)
        event_count = len(IdentityHandler.store.events)
        second = IdentityHandler.create_account(None, params)
        self.assertEqual(first, second)
        self.assertEqual(len(IdentityHandler.store.events), event_count)
        self.assertEqual(len(IdentityHandler.store.items), 2)

    def test_creation_rejects_permanent_passwords(self):
        before = len(IdentityHandler.store.items)
        with self.assertRaisesRegex(ValueError, "passwords cannot be set"):
            self.request(
                {
                    "displayName": "Password Attempt",
                    "email": "password@example.test",
                    "participationType": "SWL",
                    "password": "Never accept this password",
                },
                self.root,
            )
        self.assertEqual(len(IdentityHandler.store.items), before)

    def test_identity_admin_cannot_grant_a_role_with_unheld_authority(self):
        actor = self.new_identity_admin()
        before = len(IdentityHandler.store.items)
        with self.assertRaisesRegex(PermissionError, "strictly below"):
            self.request(
                {
                    "displayName": "Escalation Attempt",
                    "email": "escalation@example.test",
                    "participationType": "OPERATOR",
                    "roles": [{"role": "GIS_ADMIN"}],
                },
                actor,
            )
        self.assertEqual(len(IdentityHandler.store.items), before)

    def test_identity_admin_cannot_regrant_equal_authority_role(self):
        actor = self.new_identity_admin()
        before = len(IdentityHandler.store.items)
        with self.assertRaisesRegex(PermissionError, "strictly below"):
            self.request(
                {
                    "displayName": "Equal authority attempt",
                    "email": "equal-authority@example.test",
                    "participationType": "OPERATOR",
                    "roles": [{"role": "IDENTITY_ADMIN"}],
                },
                actor,
            )
        self.assertEqual(len(IdentityHandler.store.items), before)

    def test_identity_admin_can_preserve_or_revoke_an_existing_higher_role(
        self,
    ):
        actor = self.new_identity_admin()
        target = {
            "id": "another-identity-admin",
            "displayName": "Another Identity Admin",
            "email": "another-identity-admin@example.test",
            "participationType": "OPERATOR",
            "status": "ACTIVE",
            "callsigns": [],
            "primaryCallsignId": None,
        }
        IdentityHandler.store.items[target["id"]] = target
        target_assignment = {
            "id": "target-identity-role",
            "accountId": target["id"],
            "role": "IDENTITY_ADMIN",
            "programmeSlug": None,
            "jurisdiction": None,
            "entityType": None,
            "scopes": IdentityHandler._role_definition("IDENTITY_ADMIN")[
                "scopes"
            ],
            "createdAt": "2026-01-01T00:00:00Z",
            "validTo": None,
        }
        IdentityHandler._bucket("roles")[target_assignment["id"]] = (
            target_assignment
        )
        request = {
            "Authorization": "Bearer " + self.token(actor),
            "_http": "1",
        }

        retained = IdentityHandler._replace_roles(
            target["id"],
            [{"code": "IDENTITY_ADMIN"}, {"code": "PARTICIPANT"}],
            request,
        )
        self.assertEqual(
            {role["role"] for role in retained},
            {"IDENTITY_ADMIN", "PARTICIPANT"},
        )
        revoked = IdentityHandler._replace_roles(
            target["id"], [{"code": "PARTICIPANT"}], request
        )
        self.assertEqual([role["role"] for role in revoked], ["PARTICIPANT"])

    def test_global_operator_cannot_grant_equal_global_operator_role(self):
        before = len(IdentityHandler.store.items)
        with self.assertRaisesRegex(PermissionError, "strictly below"):
            self.request(
                {
                    "displayName": "Global Escalation Attempt",
                    "email": "global-escalation@example.test",
                    "participationType": "OPERATOR",
                    "roles": [{"role": "GLOBAL_OPERATOR"}],
                },
                self.root,
            )
        self.assertEqual(len(IdentityHandler.store.items), before)

    def test_role_grant_cannot_target_the_actor(self):
        token = self.token(self.root)
        with self.assertRaisesRegex(PermissionError, "themselves"):
            IdentityHandler.assign_role(
                None,
                {
                    "_body": {"role": "PARTICIPANT"},
                    "_http": "1",
                    "Authorization": "Bearer " + token,
                    "accountId": self.root["id"],
                },
            )

    def test_access_token_uses_current_roles_without_refresh(self):
        actor = self.new_identity_admin()
        token = self.token(actor)
        assignment = next(
            role
            for role in IdentityHandler._roles(actor["id"])
            if role["role"] == "IDENTITY_ADMIN"
        )
        assignment["validTo"] = "2026-10-14T00:00:00Z"
        with self.assertRaisesRegex(PermissionError, "required scope"):
            IdentityHandler._auth(
                {
                    "Authorization": "Bearer " + token,
                    "_http": "1",
                },
                scopes=("identity.accounts.create",),
            )

    def test_admin_account_list_returns_identity_resolved_effective_scopes(
        self,
    ):
        result = IdentityHandler.list_admin_accounts(
            None,
            {
                "Authorization": "Bearer " + self.token(self.root),
                "_http": "1",
                "_path": "/v1/identity/admin/accounts",
            },
        )
        root = next(
            item for item in result["items"] if item["id"] == self.root["id"]
        )
        self.assertEqual(
            root["scopes"], IdentityHandler._scopes(self.root["id"])
        )
        self.assertIn("*", root["scopes"])

    def test_access_token_for_deactivated_account_is_rejected(self):
        token = self.token(self.root)
        self.root["status"] = "DEACTIVATED"
        with self.assertRaisesRegex(PermissionError, "inactive"):
            IdentityHandler._auth(
                {"Authorization": "Bearer " + token, "_http": "1"}
            )

    def test_public_registration_remains_disabled_until_prerequisites_exist(
        self,
    ):
        with self.assertRaisesRegex(PermissionError, "email verification"):
            IdentityHandler.register(None, {"_body": {}})


if __name__ == "__main__":
    unittest.main()
