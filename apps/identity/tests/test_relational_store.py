"""Cross-connection tests for Identity's authoritative PostgreSQL store."""

from __future__ import annotations

import os
import threading
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from identity import IdentityHandler
from relational_store import IdentityStore


ROOT = Path(__file__).resolve().parents[3]
BASELINE = ROOT / "deploy/db/migrations/core/001_core_baseline.sql"
SCHEMA = ROOT / "deploy/db/migrations/core/002_identity_auth_support.sql"
BACKFILL = ROOT / "deploy/db/migrations/core/003_identity_auth_backfill.sql"


class IdentityRelationalStoreTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not os.environ.get("PGHOST"):
            raise unittest.SkipTest(
                "PostgreSQL test service is not configured"
            )
        cls.admin_options = {
            "host": os.environ["PGHOST"],
            "port": os.environ.get("PGPORT", "5432"),
            "user": os.environ.get("PGUSER", "postgres"),
            "password": os.environ.get("PGPASSWORD", "postgres"),
            "dbname": os.environ.get("PGDATABASE", "postgres"),
        }

    def setUp(self) -> None:
        self.database = f"identity_runtime_{uuid.uuid4().hex}"
        with psycopg.connect(**self.admin_options, autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(
                    sql.Identifier(self.database)
                )
            )
        options = {**self.admin_options, "dbname": self.database}
        with psycopg.connect(**options) as connection:
            connection.execute(BASELINE.read_text(), prepare=False)
            connection.commit()
            connection.execute(SCHEMA.read_text(), prepare=False)
            connection.commit()
            connection.execute(BACKFILL.read_text(), prepare=False)
            connection.commit()
            # A post-backfill legacy snapshot must not become runtime authority.
            connection.execute(
                "INSERT INTO public.service_state(service, state) VALUES "
                "('identity', %s)",
                (Jsonb({"items": {"legacy-only": {"id": "legacy-only"}}}),),
            )
        self.dsn = psycopg.conninfo.make_conninfo(**options)
        self.stores: list[IdentityStore] = []

    def tearDown(self) -> None:
        for store in self.stores:
            store.close()
        with psycopg.connect(**self.admin_options, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                    sql.Identifier(self.database)
                )
            )

    def new_store(self) -> IdentityStore:
        previous = os.environ.get("CORE_DATABASE_URL")
        os.environ["CORE_DATABASE_URL"] = self.dsn
        try:
            store = IdentityStore()
        finally:
            if previous is None:
                os.environ.pop("CORE_DATABASE_URL", None)
            else:
                os.environ["CORE_DATABASE_URL"] = previous
        self.stores.append(store)
        return store

    @staticmethod
    def account(account_id: str, email: str) -> dict:
        call_id = str(uuid.uuid4())
        return {
            "id": account_id,
            "displayName": "Relational Test Operator",
            "email": email,
            "participationType": "OPERATOR",
            "status": "ACTIVE",
            "createdAt": "2026-01-01T00:00:00Z",
            "updatedAt": "2026-01-01T00:00:00Z",
            "websiteUrl": "https://example.test/operator",
            "biographyMarkdown": "test profile",
            "profileImage": None,
            "callsigns": [
                {
                    "id": call_id,
                    "value": "N0REL",
                    "status": "VERIFIED",
                    "verificationSource": "operator-review",
                    "verifiedAt": "2026-01-01T00:00:00Z",
                    "validFrom": "2026-01-01T00:00:00Z",
                    "validTo": None,
                    "evidenceIds": [],
                }
            ],
            "primaryCallsignId": call_id,
        }

    def test_state_is_shared_across_store_instances_and_never_uses_snapshot(
        self,
    ):
        first, second = self.new_store(), self.new_store()
        account_id = str(uuid.uuid4())
        account = self.account(account_id, "shared@example.test")
        role_id = str(uuid.uuid4())
        session_id = str(uuid.uuid4())
        access_jti = str(uuid.uuid4())
        evidence_id = str(uuid.uuid4())
        oidc_id = str(uuid.uuid4())
        rate_key = "a" * 64

        with first.operation(write=True):
            self.assertNotIn("legacy-only", first.items)
            first.items[account_id] = account
            first.data["credentials"][account_id] = {
                "passwordHash": "argon2id$test-hash",
                "passwordChangedAt": "2026-01-01T00:00:00Z",
                "failedAttempts": 2,
                "lockedUntil": None,
            }
            first.data["roles"][role_id] = {
                "id": role_id,
                "accountId": account_id,
                "role": "GLOBAL_OPERATOR",
                "programmeSlug": None,
                "jurisdiction": None,
                "entityType": None,
                "scopes": ["identity.admin"],
                "createdAt": "2026-01-01T00:00:00Z",
                "validTo": None,
            }
            first.data["roleDefinitions"]["GLOBAL_OPERATOR"] = {
                "code": "GLOBAL_OPERATOR",
                "name": "Global operator",
                "description": "Test role",
                "scopes": ["identity.admin"],
                "system": True,
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-01T00:00:00Z",
            }
            first.data["sessions"][session_id] = {
                "id": session_id,
                "accountId": account_id,
                "refreshHash": "b" * 64,
                "accessJti": access_jti,
                "createdAt": "2026-01-01T00:00:00Z",
                "expiresAt": "2027-01-01T00:00:00Z",
                "revokedAt": None,
                "userAgent": "integration-test",
                "remoteAddr": "192.0.2.10",
            }
            first.data["revokedJti"][str(uuid.uuid4())] = {
                "expiresAt": 1_800_000_000
            }
            first.data["recovery"]["c" * 64] = {
                "accountId": account_id,
                "expiresAt": "2027-01-01T00:00:00Z",
                "usedAt": None,
            }
            first.data["rateLimits"][rate_key] = {
                "windowStart": 1_800_000_000,
                "count": 3,
                "expiresAt": 1_800_000_900,
            }
            first.data["callsignEvidence"][evidence_id] = {
                "id": evidence_id,
                "callsignId": account["callsigns"][0]["id"],
                "accountId": account_id,
                "evidenceType": "LICENSE",
                "source": "national-regulator",
                "checksum": "d" * 64,
                "metadata": {"test": True},
                "status": "PENDING",
                "submittedAt": "2026-01-01T00:00:00Z",
                "reviewedAt": None,
            }
            security_event_id = str(uuid.uuid4())
            first.data["securityEvents"][security_event_id] = {
                "id": security_event_id,
                "eventType": "identity.test.v1",
                "occurredAt": "2026-01-01T00:00:00Z",
                "payload": {"accountId": account_id},
            }
            first.data["oidcMappings"][oidc_id] = {
                "id": oidc_id,
                "programmeSlug": "regional-ota",
                "issuer": "https://issuer.example.test",
                "clientId": "myota-test",
                "scopes": ["openid", "profile"],
                "enabled": True,
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-01T00:00:00Z",
            }
            first.idempotency["create-account-test"] = {"created": True}
            first.event(
                "identity.test.persisted.v1",
                "account",
                account_id,
                {"accountId": account_id},
            )

        with second.operation(write=False):
            self.assertEqual(
                second.items[account_id]["email"], "shared@example.test"
            )
            self.assertEqual(
                second.items[account_id]["primaryCallsignId"],
                account["primaryCallsignId"],
            )
            self.assertEqual(
                second.data["credentials"][account_id]["failedAttempts"], 2
            )
            self.assertIn(role_id, second.data["roles"])
            self.assertIn(session_id, second.data["sessions"])
            self.assertEqual(second.data["rateLimits"][rate_key]["count"], 3)
            self.assertIn(evidence_id, second.data["callsignEvidence"])
            self.assertIn(oidc_id, second.data["oidcMappings"])
            self.assertEqual(
                second.idempotency["create-account-test"], {"created": True}
            )
            self.assertEqual(second.events, [])

        with second.operation(write=True):
            second.data["credentials"][account_id]["failedAttempts"] = 4
            second.data["sessions"][session_id]["revokedAt"] = (
                "2026-01-02T00:00:00Z"
            )
            second.data["roles"][role_id]["validTo"] = "2026-01-02T00:00:00Z"

        with first.operation(write=False):
            self.assertEqual(
                first.data["credentials"][account_id]["failedAttempts"], 4
            )
            self.assertIsNotNone(
                first.data["sessions"][session_id]["revokedAt"]
            )
            self.assertIsNotNone(first.data["roles"][role_id]["validTo"])

        with psycopg.connect(self.dsn) as connection:
            legacy = connection.execute(
                "SELECT state FROM public.service_state WHERE service = 'identity'"
            ).fetchone()[0]
            self.assertEqual(
                legacy, {"items": {"legacy-only": {"id": "legacy-only"}}}
            )

    def test_concurrent_instances_serialize_normalized_email_creation(self):
        stores = [self.new_store(), self.new_store()]
        barrier = threading.Barrier(2)
        outcomes: list[str] = []
        failures: list[BaseException] = []

        def create(store: IdentityStore, account_id: str) -> None:
            try:
                barrier.wait(timeout=10)
                with store.operation(write=True):
                    if any(
                        account.get("email", "").casefold()
                        == "race@example.test"
                        for account in store.items.values()
                    ):
                        outcomes.append("duplicate-rejected")
                        return
                    store.items[account_id] = self.account(
                        account_id, "Race@Example.Test"
                    )
                    outcomes.append("created")
            except BaseException as exc:
                failures.append(exc)

        threads = [
            threading.Thread(target=create, args=(store, str(uuid.uuid4())))
            for store in stores
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)

        self.assertFalse(any(thread.is_alive() for thread in threads))
        self.assertEqual(failures, [])
        self.assertCountEqual(outcomes, ["created", "duplicate-rejected"])
        with stores[0].operation(write=False):
            self.assertEqual(
                sum(
                    account.get("email", "").casefold() == "race@example.test"
                    for account in stores[0].items.values()
                ),
                1,
            )

    def test_login_lockout_and_refresh_rotation_cross_instances(self):
        first, second = self.new_store(), self.new_store()
        previous_store = IdentityHandler.store
        account_id = str(uuid.uuid4())
        password = "Relational Identity Password 2026!"
        account = self.account(account_id, "auth@example.test")
        try:
            IdentityHandler.store = first
            with first.operation(write=True):
                first.items[account_id] = account
                IdentityHandler._set_password(account_id, password)

            with first.operation(write=True):
                logged_in = IdentityHandler.login(
                    None,
                    {
                        "_body": {
                            "email": "auth@example.test",
                            "password": password,
                        },
                        "Remote-Addr": "192.0.2.10",
                    },
                )

            IdentityHandler.store = second
            with second.operation(write=True):
                rotated = IdentityHandler.refresh(
                    None,
                    {"_body": {"refreshToken": logged_in["refreshToken"]}},
                )
            IdentityHandler.store = first
            with self.assertRaisesRegex(PermissionError, "invalid or revoked"):
                with first.operation(write=True):
                    IdentityHandler.refresh(
                        None,
                        {"_body": {"refreshToken": logged_in["refreshToken"]}},
                    )

            for attempt in range(5):
                store = first if attempt % 2 == 0 else second
                IdentityHandler.store = store
                with self.assertRaisesRegex(ValueError, "invalid credentials"):
                    with store.operation(write=True):
                        IdentityHandler.login(
                            None,
                            {
                                "_body": {
                                    "email": "auth@example.test",
                                    "password": "incorrect password",
                                },
                                "Remote-Addr": "192.0.2.10",
                            },
                        )

            IdentityHandler.store = first
            with first.operation(write=False):
                credential = first.data["credentials"][account_id]
                self.assertEqual(credential["failedAttempts"], 5)
                self.assertIsNotNone(credential["lockedUntil"])
                self.assertTrue(rotated["refreshToken"])
        finally:
            IdentityHandler.store = previous_store

    def test_missing_backfill_marker_fails_closed(self):
        store = self.new_store()
        with psycopg.connect(self.dsn) as connection:
            connection.execute(
                "DELETE FROM public.identity_auth_state_migration "
                "WHERE migration_name = 'service-state-jsonb-v1'"
            )
        with self.assertRaisesRegex(RuntimeError, "refusing JSONB fallback"):
            with store.operation(write=False):
                self.fail("an unbackfilled store must not serve requests")


if __name__ == "__main__":
    unittest.main()
