"""Exercise the Core Identity auth migration against an isolated PostgreSQL DB."""

from __future__ import annotations

import os
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import errors, sql
from psycopg.types.json import Jsonb


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "db/migrations/core/001_core_baseline.sql"
MIGRATION = ROOT / "db/migrations/core/002_identity_auth_support.sql"
BACKFILL = ROOT / "db/migrations/core/003_identity_auth_backfill.sql"


class IdentityAuthMigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not os.environ.get("PGHOST"):
            raise unittest.SkipTest("PostgreSQL test service is not configured")
        cls.connection_options = {
            "host": os.environ["PGHOST"],
            "port": os.environ.get("PGPORT", "5432"),
            "user": os.environ.get("PGUSER", "postgres"),
            "password": os.environ.get("PGPASSWORD", "postgres"),
            "dbname": os.environ.get("PGDATABASE", "postgres"),
        }
        cls.databases: list[str] = []

    @classmethod
    def tearDownClass(cls) -> None:
        with psycopg.connect(**cls.connection_options, autocommit=True) as conn:
            for database in cls.databases:
                conn.execute(
                    sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(
                        sql.Identifier(database)
                    )
                )

    def _new_database(self) -> psycopg.Connection:
        name = f"identity_migration_{uuid.uuid4().hex}"
        with psycopg.connect(**self.connection_options, autocommit=True) as admin:
            admin.execute(
                sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name))
            )
        self.databases.append(name)
        options = {**self.connection_options, "dbname": name}
        return psycopg.connect(**options)

    def _apply_baseline(self, conn: psycopg.Connection) -> None:
        conn.execute(BASELINE.read_text(), prepare=False)
        conn.commit()

    def test_migration_adds_identity_constraints_and_tables(self) -> None:
        with self._new_database() as conn:
            self._apply_baseline(conn)
            with conn.transaction():
                conn.execute(MIGRATION.read_text(), prepare=False)

            tables = {
                row[0]
                for row in conn.execute(
                    """SELECT table_name FROM information_schema.tables
                         WHERE table_schema='public'"""
                ).fetchall()
            }
            self.assertTrue(
                {
                    "identity_role_definition",
                    "identity_account_profile",
                    "identity_login_rate_limit",
                }.issubset(tables)
            )
            columns = {
                row[0]
                for row in conn.execute(
                    """SELECT column_name FROM information_schema.columns
                         WHERE table_schema='public' AND table_name='account'"""
                ).fetchall()
            }
            self.assertIn("identity_email_key", columns)

            account_id = uuid.uuid4()
            conn.execute(
                """INSERT INTO public.account
                   (id, display_name, email, identity_email_key, participation_type)
                   VALUES (%s, 'First', 'first@example.test', 'first@example.test', 'OPERATOR')""",
                (account_id,),
            )
            with self.assertRaises(errors.UniqueViolation):
                with conn.transaction():
                    conn.execute(
                        """INSERT INTO public.account
                           (display_name, email, identity_email_key, participation_type)
                           VALUES ('Duplicate', 'FIRST@example.test', 'FIRST@example.test', 'SWL')"""
                    )

            with self.assertRaises(errors.CheckViolation):
                with conn.transaction():
                    conn.execute(
                        """INSERT INTO public.identity_login_rate_limit
                           (key_hash, window_started_at, request_count, expires_at)
                           VALUES ('bad-hash', now(), 1, now() + interval '15 minutes')"""
                    )

    def test_duplicate_legacy_emails_abort_before_schema_cutover(self) -> None:
        with self._new_database() as conn:
            self._apply_baseline(conn)
            conn.execute(
                """INSERT INTO public.account
                   (display_name, email, participation_type)
                   VALUES ('First', 'same@example.test', 'OPERATOR'),
                          ('Second', 'SAME@example.test', 'SWL')"""
            )
            conn.commit()

            with self.assertRaises(errors.RaiseException) as raised:
                with conn.transaction():
                    conn.execute(MIGRATION.read_text(), prepare=False)
            self.assertIn(
                "duplicate normalized Identity email", str(raised.exception)
            )
            self.assertFalse(
                conn.execute(
                    """SELECT 1 FROM information_schema.columns
                         WHERE table_schema='public' AND table_name='account'
                           AND column_name='identity_email_key'"""
                ).fetchone()
            )

    def test_backfill_preserves_auth_state_and_is_restartable(self) -> None:
        account_id = uuid.uuid4()
        deactivated_account_id = uuid.uuid4()
        callsign_id = uuid.uuid4()
        evidence_id = uuid.uuid4()
        role_id = uuid.uuid4()
        session_id = uuid.uuid4()
        access_jti = uuid.uuid4()
        revoked_jti = uuid.uuid4()
        oidc_id = uuid.uuid4()
        event_id = uuid.uuid4()
        security_event_id = uuid.uuid4()
        occurred_at = "2026-01-02T03:04:05Z"
        legacy = {
            "items": {
                str(account_id): {
                    "id": str(account_id),
                    "displayName": "Example Operator",
                    "email": "  Operator@Example.test ",
                    "participationType": "OPERATOR",
                    "status": "ACTIVE",
                    "createdAt": occurred_at,
                    "updatedAt": occurred_at,
                    "callsigns": [
                        {
                            "id": str(callsign_id),
                            "value": "N0TEST",
                            "status": "VERIFIED",
                            "verificationSource": "manual-review",
                            "verifiedAt": occurred_at,
                            "validFrom": occurred_at,
                            "validTo": None,
                        }
                    ],
                    "primaryCallsignId": str(callsign_id),
                },
                str(deactivated_account_id): {
                    "id": str(deactivated_account_id),
                    "displayName": "Deactivated Account",
                    "email": None,
                    "participationType": "SWL",
                    "status": "DEACTIVATED",
                },
            },
            "events": [
                {
                    "eventId": str(event_id),
                    "eventType": "identity.account.created.v1",
                    "producer": "identity",
                    "aggregate": {"type": "account", "id": str(account_id)},
                    "payload": {"accountId": str(account_id)},
                    "occurredAt": occurred_at,
                    "correlationId": "identity-migration-test",
                }
            ],
            "data": {
                "credentials": {
                    str(account_id): {
                        "passwordHash": "argon2id$test-hash",
                        "passwordChangedAt": occurred_at,
                        "failedAttempts": 2,
                        "lockedUntil": None,
                    }
                },
                "roleDefinitions": {
                    "GLOBAL_OPERATOR": {
                        "name": "Global operator",
                        "description": "Platform-wide administration.",
                        "scopes": ["identity.admin", "identity.me"],
                        "system": True,
                        "createdAt": occurred_at,
                        "updatedAt": occurred_at,
                    }
                },
                "roles": {
                    str(role_id): {
                        "id": str(role_id),
                        "accountId": str(account_id),
                        "role": "GLOBAL_OPERATOR",
                        "programmeSlug": "winter-series",
                        "jurisdiction": "DE-BE",
                        "entityType": "PARK",
                        "scopes": ["identity.admin"],
                        "createdAt": occurred_at,
                        "validTo": None,
                    }
                },
                "sessions": {
                    str(session_id): {
                        "id": str(session_id),
                        "accountId": str(account_id),
                        "refreshHash": "refresh-hash",
                        "accessJti": str(access_jti),
                        "createdAt": occurred_at,
                        "expiresAt": "2027-01-02T03:04:05Z",
                        "revokedAt": None,
                        "userAgent": "migration-test",
                        "remoteAddr": "192.0.2.10",
                    }
                },
                "revokedJti": {
                    str(revoked_jti): {"expiresAt": 1790000000}
                },
                "recovery": {
                    "recovery-hash": {
                        "accountId": str(account_id),
                        "expiresAt": "2027-01-02T03:04:05Z",
                        "usedAt": None,
                    }
                },
                "rateLimits": {
                    "192.0.2.10": {"windowStart": 1767323045, "count": 3}
                },
                "callsignEvidence": {
                    str(evidence_id): {
                        "id": str(evidence_id),
                        "callsignId": str(callsign_id),
                        "accountId": str(account_id),
                        "evidenceType": "LICENSE",
                        "source": "operator-upload",
                        "checksum": "abc123",
                        "metadata": {"country": "DE"},
                        "status": "ACCEPTED",
                        "submittedAt": occurred_at,
                        "reviewedAt": occurred_at,
                    }
                },
                "oidcMappings": {
                    str(oidc_id): {
                        "id": str(oidc_id),
                        "programmeSlug": "winter-series",
                        "issuer": "https://issuer.example.test",
                        "clientId": "myota-test-client",
                        "scopes": ["openid", "profile"],
                        "enabled": True,
                        "createdAt": occurred_at,
                        "updatedAt": occurred_at,
                    }
                },
                "securityEvents": {
                    str(security_event_id): {
                        "id": str(security_event_id),
                        "eventType": "identity.login.succeeded.v1",
                        "payload": {"accountId": str(account_id)},
                        "occurredAt": occurred_at,
                    }
                },
            },
            "idempotency": {"request-key": {"status": "created"}},
        }

        with self._new_database() as conn:
            self._apply_baseline(conn)
            with conn.transaction():
                conn.execute(MIGRATION.read_text(), prepare=False)
            conn.execute(
                "INSERT INTO public.service_state(service, state) VALUES ('identity', %s)",
                (Jsonb(legacy),),
            )
            conn.commit()

            for _ in range(2):
                with conn.transaction():
                    conn.execute(BACKFILL.read_text(), prepare=False)

            account = conn.execute(
                "SELECT display_name, email::text, identity_email_key FROM public.account WHERE id=%s",
                (account_id,),
            ).fetchone()
            self.assertEqual(
                account,
                ("Example Operator", "operator@example.test", "operator@example.test"),
            )
            self.assertEqual(
                conn.execute(
                    "SELECT password_hash, failed_attempts FROM public.account_credential WHERE account_id=%s",
                    (account_id,),
                ).fetchone(),
                ("argon2id$test-hash", 2),
            )
            self.assertEqual(
                conn.execute(
                    "SELECT programme_slug, jurisdiction_code, entity_type_code FROM public.account_role WHERE id=%s",
                    (role_id,),
                ).fetchone(),
                ("winter-series", "DE-BE", "PARK"),
            )
            self.assertEqual(
                conn.execute(
                    "SELECT refresh_token_hash FROM public.auth_session WHERE id=%s",
                    (session_id,),
                ).fetchone()[0],
                "refresh-hash",
            )
            self.assertEqual(
                conn.execute(
                    "SELECT callsign_id FROM public.account_primary_callsign WHERE account_id=%s",
                    (account_id,),
                ).fetchone()[0],
                callsign_id,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM public.identity_auth_state_migration WHERE migration_name='service-state-jsonb-v1'"
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM public.outbox_event WHERE event_id=%s",
                    (event_id,),
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM public.security_event WHERE id=%s",
                    (security_event_id,),
                ).fetchone()[0],
                1,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM public.identity_oidc_provider_mapping WHERE id=%s",
                    (oidc_id,),
                ).fetchone()[0],
                1,
            )
            marker = conn.execute(
                "SELECT source_sha256, source_counts, target_counts FROM public.identity_auth_state_migration WHERE migration_name='service-state-jsonb-v1'"
            ).fetchone()
            self.assertRegex(marker[0], r"^[0-9a-f]{64}$")
            self.assertEqual(marker[1]["accounts"], 2)
            self.assertEqual(marker[1]["credentials"], 1)
            self.assertEqual(marker[1]["sessions"], 1)
            self.assertEqual(marker[2]["accounts"], 2)
            self.assertEqual(marker[2]["credentials"], 1)
            self.assertEqual(marker[2]["sessions"], 1)
            self.assertEqual(
                conn.execute(
                    "SELECT response FROM public.idempotency_record WHERE service='identity' AND key='request-key'"
                ).fetchone()[0],
                {"status": "created"},
            )

    def test_backfill_rejects_duplicate_json_emails_atomically(self) -> None:
        first_id, second_id = uuid.uuid4(), uuid.uuid4()
        legacy = {
            "items": {
                str(first_id): {
                    "id": str(first_id),
                    "displayName": "First",
                    "email": "same@example.test",
                    "participationType": "OPERATOR",
                },
                str(second_id): {
                    "id": str(second_id),
                    "displayName": "Second",
                    "email": "SAME@example.test",
                    "participationType": "SWL",
                },
            },
            "data": {},
            "events": [],
        }
        with self._new_database() as conn:
            self._apply_baseline(conn)
            with conn.transaction():
                conn.execute(MIGRATION.read_text(), prepare=False)
            conn.execute(
                "INSERT INTO public.service_state(service, state) VALUES ('identity', %s)",
                (Jsonb(legacy),),
            )
            conn.commit()

            with self.assertRaises(errors.RaiseException) as raised:
                with conn.transaction():
                    conn.execute(BACKFILL.read_text(), prepare=False)
            self.assertIn("duplicate normalized Identity emails", str(raised.exception))
            self.assertEqual(
                conn.execute("SELECT count(*) FROM public.account").fetchone()[0],
                0,
            )
            self.assertEqual(
                conn.execute(
                    "SELECT count(*) FROM public.identity_auth_state_migration"
                ).fetchone()[0],
                0,
            )


if __name__ == "__main__":
    unittest.main()
