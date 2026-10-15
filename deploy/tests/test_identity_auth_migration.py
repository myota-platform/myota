"""Exercise the Core Identity auth migration against an isolated PostgreSQL DB."""

from __future__ import annotations

import os
import unittest
import uuid
from pathlib import Path

import psycopg
from psycopg import errors, sql


ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "db/migrations/core/001_core_baseline.sql"
MIGRATION = ROOT / "db/migrations/core/002_identity_auth_support.sql"


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


if __name__ == "__main__":
    unittest.main()
