"""PostgreSQL-authoritative, request-scoped Identity state.

Handlers keep their existing dictionary-shaped projections, but those
projections are loaded inside a database transaction for each operation. A
transaction-scoped advisory lock serializes mutations across Identity replicas;
only changed projections are written back to their owning relational tables.
"""

from __future__ import annotations

import copy
import hashlib
import json
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from common import Store


MIGRATION_NAME = "service-state-jsonb-v1"


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


class IdentityStore(Store):
    """Request transaction adapter for Identity-owned relational records."""

    def __init__(self) -> None:
        super().__init__("identity", "CORE_DATABASE_URL")
        self._operation_lock = threading.RLock()
        self._connection: Any = None
        self._before: dict[str, Any] | None = None
        self._write_allowed = False
        self._after_commit: list[Any] = []

    def hydrate(self) -> None:
        # Identity never hydrates the legacy service_state aggregate.
        if self.durable and self._connection is None:
            raise RuntimeError(
                "Identity state must be loaded inside a relational operation"
            )

    @contextmanager
    def operation(self, write: bool = False) -> Iterator[None]:
        if not self.durable:
            yield
            return
        with self._operation_lock:
            callbacks: list[Any] = []
            committed_error: Exception | None = None
            with self.transaction() as connection:
                if write:
                    connection.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                        ("myota:identity:authoritative-state",),
                    )
                else:
                    connection.execute(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"
                    )
                marker = connection.execute(
                    "SELECT 1 FROM public.identity_auth_state_migration "
                    "WHERE migration_name = %s",
                    (MIGRATION_NAME,),
                ).fetchone()
                if not marker:
                    raise RuntimeError(
                        "Identity relational backfill is not complete; "
                        "refusing JSONB fallback"
                    )
                self._connection = connection
                self._after_commit = []
                self._load(connection)
                self._before = self._snapshot()
                self._write_allowed = write
                try:
                    yield
                except Exception as exc:
                    if write and getattr(exc, "commit_operation", False):
                        self.persist()
                        committed_error = exc
                    else:
                        raise
                else:
                    if write:
                        self.persist()
                finally:
                    self._connection = None
                    self._before = None
                    self._write_allowed = False
                    callbacks = self._after_commit
                    self._after_commit = []
            for callback in callbacks:
                try:
                    callback()
                except Exception:
                    # Profile image cleanup is retried by the orphan sweeper.
                    pass
            if committed_error is not None:
                raise committed_error

    def after_commit(self, callback: Any) -> None:
        """Run an external side effect only after its row change commits."""
        if self._connection is None:
            callback()
        else:
            self._after_commit.append(callback)

    def _snapshot(self) -> dict[str, Any]:
        return {
            "items": copy.deepcopy(self.items),
            "events": copy.deepcopy(self.events),
            "data": copy.deepcopy(self.data),
            "idempotency": copy.deepcopy(self.idempotency),
        }

    def _load(self, connection: Any) -> None:
        accounts: dict[str, dict[str, Any]] = {}
        for row in connection.execute(
            "SELECT a.id, a.display_name, a.email, a.participation_type, "
            "a.status, a.created_at, a.updated_at, p.website_url, "
            "p.biography_markdown, p.profile_image_id, "
            "p.profile_image_media_type, p.profile_image_updated_at, "
            "pc.callsign_id "
            "FROM public.account AS a "
            "LEFT JOIN public.identity_account_profile AS p "
            "ON p.account_id = a.id "
            "LEFT JOIN public.account_primary_callsign AS pc "
            "ON pc.account_id = a.id"
        ).fetchall():
            (
                account_id,
                display_name,
                email,
                participation_type,
                status,
                created_at,
                updated_at,
                website_url,
                biography,
                image_id,
                image_type,
                image_updated,
                primary_callsign_id,
            ) = row
            account_id = str(account_id)
            accounts[account_id] = {
                "id": account_id,
                "displayName": display_name,
                "email": email,
                "participationType": participation_type,
                "status": status,
                "createdAt": _iso(created_at),
                "updatedAt": _iso(updated_at),
                "websiteUrl": website_url,
                "biographyMarkdown": biography,
                "callsigns": [],
                "primaryCallsignId": (
                    str(primary_callsign_id) if primary_callsign_id else None
                ),
            }
            if image_id:
                accounts[account_id]["profileImage"] = {
                    "id": str(image_id),
                    "contentType": image_type,
                    "updatedAt": _iso(image_updated),
                }
        for row in connection.execute(
            "SELECT id, account_id, value, lifecycle_status, "
            "verification_source, verified_at, valid_from, valid_to "
            "FROM public.callsign"
        ).fetchall():
            (
                callsign_id,
                account_id,
                value,
                status,
                source,
                verified_at,
                valid_from,
                valid_to,
            ) = row
            account = accounts.get(str(account_id))
            if account is not None:
                account["callsigns"].append(
                    {
                        "id": str(callsign_id),
                        "value": value,
                        "status": status,
                        "verificationSource": source,
                        "verifiedAt": _iso(verified_at),
                        "validFrom": _iso(valid_from),
                        "validTo": _iso(valid_to),
                    }
                )
        self.items = accounts

        data: dict[str, dict[str, Any]] = {
            name: {}
            for name in (
                "credentials",
                "roleDefinitions",
                "roles",
                "sessions",
                "revokedJti",
                "recovery",
                "rateLimits",
                "callsignEvidence",
                "securityEvents",
                "oidcMappings",
            )
        }
        for (
            account_id,
            password_hash,
            changed_at,
            failed,
            locked_until,
        ) in connection.execute(
            "SELECT account_id, password_hash, password_changed_at, "
            "failed_attempts, locked_until FROM public.account_credential"
        ).fetchall():
            data["credentials"][str(account_id)] = {
                "passwordHash": password_hash,
                "passwordChangedAt": _iso(changed_at),
                "failedAttempts": failed,
                "lockedUntil": _iso(locked_until),
            }
        for (
            code,
            name,
            description,
            scopes,
            system,
            created,
            updated,
        ) in connection.execute(
            "SELECT role_code, display_name, description, scopes, is_system, "
            "created_at, updated_at FROM public.identity_role_definition"
        ).fetchall():
            data["roleDefinitions"][code] = {
                "code": code,
                "name": name,
                "description": description,
                "scopes": list(scopes or []),
                "system": system,
                "createdAt": _iso(created),
                "updatedAt": _iso(updated),
            }
        for (
            role_id,
            account_id,
            programme,
            code,
            jurisdiction,
            entity_type,
            scopes,
            created,
            valid_to,
        ) in connection.execute(
            "SELECT id, account_id, programme_slug, role_code, "
            "jurisdiction_code, entity_type_code, scopes, created_at, valid_to "
            "FROM public.account_role"
        ).fetchall():
            data["roles"][str(role_id)] = {
                "id": str(role_id),
                "accountId": str(account_id),
                "role": code,
                "programmeSlug": programme,
                "jurisdiction": jurisdiction,
                "entityType": entity_type,
                "scopes": _json(scopes) or [],
                "createdAt": _iso(created),
                "validTo": _iso(valid_to),
            }
        for (
            session_id,
            account_id,
            refresh_hash,
            access_jti,
            created,
            expires,
            revoked,
            user_agent,
            remote_addr,
        ) in connection.execute(
            "SELECT id, account_id, refresh_token_hash, access_jti, created_at, "
            "expires_at, revoked_at, user_agent, remote_addr "
            "FROM public.auth_session"
        ).fetchall():
            data["sessions"][str(session_id)] = {
                "id": str(session_id),
                "accountId": str(account_id),
                "refreshHash": refresh_hash,
                "accessJti": str(access_jti),
                "createdAt": _iso(created),
                "expiresAt": _iso(expires),
                "revokedAt": _iso(revoked),
                "userAgent": user_agent,
                "remoteAddr": str(remote_addr) if remote_addr else None,
            }
        for jti, expires in connection.execute(
            "SELECT jti, expires_at FROM public.auth_revocation"
        ).fetchall():
            data["revokedJti"][str(jti)] = {
                "expiresAt": int(expires.timestamp())
            }
        for token_hash, account_id, expires, used in connection.execute(
            "SELECT token_hash, account_id, expires_at, used_at "
            "FROM public.account_recovery_token"
        ).fetchall():
            data["recovery"][token_hash] = {
                "accountId": str(account_id),
                "expiresAt": _iso(expires),
                "usedAt": _iso(used),
            }
        for key_hash, window_started, count, expires in connection.execute(
            "SELECT key_hash, window_started_at, request_count, expires_at "
            "FROM public.identity_login_rate_limit"
        ).fetchall():
            data["rateLimits"][key_hash] = {
                "windowStart": window_started.timestamp(),
                "count": count,
                "expiresAt": _iso(expires),
            }
        for (
            evidence_id,
            callsign_id,
            account_id,
            evidence_type,
            source,
            checksum,
            metadata,
            status,
            submitted,
            reviewed,
        ) in connection.execute(
            "SELECT id, callsign_id, submitted_by, evidence_type, source, "
            "checksum, metadata, status, submitted_at, reviewed_at "
            "FROM public.callsign_evidence"
        ).fetchall():
            data["callsignEvidence"][str(evidence_id)] = {
                "id": str(evidence_id),
                "callsignId": str(callsign_id),
                "accountId": str(account_id) if account_id else None,
                "evidenceType": evidence_type,
                "source": source,
                "checksum": checksum,
                "metadata": _json(metadata) or {},
                "status": status,
                "submittedAt": _iso(submitted),
                "reviewedAt": _iso(reviewed),
            }
        for (
            event_id,
            account_id,
            event_type,
            payload,
            occurred,
        ) in connection.execute(
            "SELECT id, account_id, event_type, payload, occurred_at "
            "FROM public.security_event"
        ).fetchall():
            data["securityEvents"][str(event_id)] = {
                "id": str(event_id),
                "eventType": event_type,
                "occurredAt": _iso(occurred),
                "payload": _json(payload) or {},
            }
        for (
            mapping_id,
            programme,
            issuer,
            client_id,
            scopes,
            enabled,
            created,
            updated,
        ) in connection.execute(
            "SELECT id, programme_slug, issuer, client_id, scopes, enabled, "
            "created_at, updated_at FROM public.identity_oidc_provider_mapping"
        ).fetchall():
            data["oidcMappings"][str(mapping_id)] = {
                "id": str(mapping_id),
                "programmeSlug": programme,
                "issuer": issuer,
                "clientId": client_id,
                "scopes": list(scopes or []),
                "enabled": enabled,
                "createdAt": _iso(created),
                "updatedAt": _iso(updated),
            }
        self.data = data
        self.events = []
        self.idempotency = {
            str(key): _json(response)
            for key, response in connection.execute(
                "SELECT key, response FROM public.idempotency_record "
                "WHERE service = 'identity'"
            ).fetchall()
        }

    def persist(self) -> None:
        connection = self._connection
        before = self._before
        if (
            not self.durable
            or connection is None
            or before is None
            or not self._write_allowed
        ):
            return
        old_accounts = before["items"]
        for account_id, account in self.items.items():
            if old_accounts.get(account_id) != account:
                self._write_account(connection, account)
        self._sync_callsigns(connection, old_accounts)
        self._sync_mapping(
            connection,
            before["data"].get("credentials", {}),
            self.data.get("credentials", {}),
            self._write_credential,
            "DELETE FROM public.account_credential WHERE account_id = %s",
        )
        self._sync_mapping(
            connection,
            before["data"].get("roleDefinitions", {}),
            self.data.get("roleDefinitions", {}),
            self._write_role_definition,
            "DELETE FROM public.identity_role_definition WHERE role_code = %s",
        )
        self._sync_mapping(
            connection,
            before["data"].get("roles", {}),
            self.data.get("roles", {}),
            self._write_role,
            "DELETE FROM public.account_role WHERE id = %s",
        )
        self._sync_mapping(
            connection,
            before["data"].get("sessions", {}),
            self.data.get("sessions", {}),
            self._write_session,
            "DELETE FROM public.auth_session WHERE id = %s",
        )
        self._sync_mapping(
            connection,
            before["data"].get("revokedJti", {}),
            self.data.get("revokedJti", {}),
            self._write_revocation,
            "DELETE FROM public.auth_revocation WHERE jti = %s",
        )
        self._sync_mapping(
            connection,
            before["data"].get("recovery", {}),
            self.data.get("recovery", {}),
            self._write_recovery,
            "DELETE FROM public.account_recovery_token WHERE token_hash = %s",
        )
        self._sync_mapping(
            connection,
            before["data"].get("rateLimits", {}),
            self.data.get("rateLimits", {}),
            self._write_rate_limit,
            "DELETE FROM public.identity_login_rate_limit WHERE key_hash = %s",
        )
        self._sync_mapping(
            connection,
            before["data"].get("callsignEvidence", {}),
            self.data.get("callsignEvidence", {}),
            self._write_evidence,
            "DELETE FROM public.callsign_evidence WHERE id = %s",
        )
        self._sync_mapping(
            connection,
            before["data"].get("securityEvents", {}),
            self.data.get("securityEvents", {}),
            self._write_security_event,
            "DELETE FROM public.security_event WHERE id = %s",
        )
        self._sync_mapping(
            connection,
            before["data"].get("oidcMappings", {}),
            self.data.get("oidcMappings", {}),
            self._write_oidc_mapping,
            "DELETE FROM public.identity_oidc_provider_mapping WHERE id = %s",
        )
        for event in self.events:
            connection.execute(
                "INSERT INTO public.outbox_event(event_id, event_type, producer, "
                "aggregate_type, aggregate_id, payload, occurred_at, correlation_id) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s) "
                "ON CONFLICT (event_id) DO NOTHING",
                (
                    event["eventId"],
                    event["eventType"],
                    event["producer"],
                    event["aggregate"]["type"],
                    event["aggregate"]["id"],
                    json.dumps(event["payload"]),
                    event["occurredAt"],
                    event["correlationId"],
                ),
            )
        for key, response in self.idempotency.items():
            if before["idempotency"].get(key) != response:
                connection.execute(
                    "INSERT INTO public.idempotency_record(service, key, response) "
                    "VALUES ('identity', %s, %s::jsonb) "
                    "ON CONFLICT (service, key) DO UPDATE "
                    "SET response = EXCLUDED.response",
                    (key, json.dumps(response)),
                )
        for key in before["idempotency"].keys() - self.idempotency.keys():
            connection.execute(
                "DELETE FROM public.idempotency_record "
                "WHERE service = 'identity' AND key = %s",
                (key,),
            )

    @staticmethod
    def _sync_mapping(
        connection: Any,
        before: dict[str, Any],
        current: dict[str, Any],
        writer: Any,
        delete_sql: str,
    ) -> None:
        for key, value in current.items():
            if before.get(key) != value:
                writer(connection, key, value)
        for key in before.keys() - current.keys():
            connection.execute(delete_sql, (key,))

    @staticmethod
    def _write_account(connection: Any, account: dict[str, Any]) -> None:
        account_id = account["id"]
        email = account.get("email")
        connection.execute(
            "INSERT INTO public.account(id, display_name, email, identity_email_key, "
            "participation_type, status, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET display_name = EXCLUDED.display_name, "
            "email = EXCLUDED.email, identity_email_key = EXCLUDED.identity_email_key, "
            "participation_type = EXCLUDED.participation_type, status = EXCLUDED.status, "
            "created_at = EXCLUDED.created_at, updated_at = EXCLUDED.updated_at",
            (
                account_id,
                account.get("displayName") or "",
                email,
                email.strip().casefold() if isinstance(email, str) else None,
                account.get("participationType") or "OPERATOR",
                account.get("status") or "ACTIVE",
                account.get("createdAt"),
                account.get("updatedAt"),
            ),
        )
        image = account.get("profileImage") or {}
        connection.execute(
            "INSERT INTO public.identity_account_profile(account_id, website_url, "
            "biography_markdown, profile_image_id, profile_image_media_type, "
            "profile_image_updated_at) VALUES (%s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (account_id) DO UPDATE SET website_url = EXCLUDED.website_url, "
            "biography_markdown = EXCLUDED.biography_markdown, "
            "profile_image_id = EXCLUDED.profile_image_id, "
            "profile_image_media_type = EXCLUDED.profile_image_media_type, "
            "profile_image_updated_at = EXCLUDED.profile_image_updated_at",
            (
                account_id,
                account.get("websiteUrl"),
                account.get("biographyMarkdown"),
                image.get("id"),
                image.get("contentType"),
                image.get("updatedAt"),
            ),
        )

    def _sync_callsigns(
        self, connection: Any, old_accounts: dict[str, dict[str, Any]]
    ) -> None:
        old: dict[str, tuple[str, dict[str, Any]]] = {}
        current: dict[str, tuple[str, dict[str, Any]]] = {}
        for account_id, account in old_accounts.items():
            for callsign in account.get("callsigns", []):
                old[str(callsign["id"])] = (account_id, callsign)
        for account_id, account in self.items.items():
            for callsign in account.get("callsigns", []):
                current[str(callsign["id"])] = (account_id, callsign)
        for callsign_id, (account_id, call) in current.items():
            if old.get(callsign_id) != (account_id, call):
                connection.execute(
                    "INSERT INTO public.callsign(id, account_id, value, lifecycle_status, "
                    "verification_source, verified_at, valid_from, valid_to) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (id) DO UPDATE SET account_id = EXCLUDED.account_id, "
                    "value = EXCLUDED.value, lifecycle_status = EXCLUDED.lifecycle_status, "
                    "verification_source = EXCLUDED.verification_source, "
                    "verified_at = EXCLUDED.verified_at, valid_from = EXCLUDED.valid_from, "
                    "valid_to = EXCLUDED.valid_to",
                    (
                        callsign_id,
                        account_id,
                        call.get("value"),
                        call.get("status") or "UNVERIFIED",
                        call.get("verificationSource"),
                        call.get("verifiedAt"),
                        call.get("validFrom"),
                        call.get("validTo"),
                    ),
                )
        deleted = old.keys() - current.keys()
        if deleted:
            connection.execute(
                "DELETE FROM public.account_primary_callsign "
                "WHERE callsign_id = ANY(%s::uuid[])",
                (list(deleted),),
            )
            connection.execute(
                "DELETE FROM public.callsign WHERE id = ANY(%s::uuid[])",
                (list(deleted),),
            )
        for account_id, account in self.items.items():
            callsign_id = account.get("primaryCallsignId")
            if callsign_id:
                connection.execute(
                    "INSERT INTO public.account_primary_callsign(account_id, callsign_id) "
                    "VALUES (%s, %s) ON CONFLICT (account_id) DO UPDATE "
                    "SET callsign_id = EXCLUDED.callsign_id",
                    (account_id, callsign_id),
                )
            else:
                connection.execute(
                    "DELETE FROM public.account_primary_callsign WHERE account_id = %s",
                    (account_id,),
                )

    @staticmethod
    def _write_credential(
        connection: Any, key: str, value: dict[str, Any]
    ) -> None:
        if not value.get("passwordHash"):
            connection.execute(
                "DELETE FROM public.account_credential WHERE account_id = %s",
                (key,),
            )
            return
        connection.execute(
            "INSERT INTO public.account_credential(account_id, password_hash, "
            "password_changed_at, failed_attempts, locked_until) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (account_id) DO UPDATE "
            "SET password_hash = EXCLUDED.password_hash, "
            "password_changed_at = EXCLUDED.password_changed_at, "
            "failed_attempts = EXCLUDED.failed_attempts, locked_until = EXCLUDED.locked_until",
            (
                key,
                value["passwordHash"],
                value.get("passwordChangedAt"),
                value.get("failedAttempts", 0),
                value.get("lockedUntil"),
            ),
        )

    @staticmethod
    def _write_role_definition(
        connection: Any, key: str, value: dict[str, Any]
    ) -> None:
        connection.execute(
            "INSERT INTO public.identity_role_definition(role_code, display_name, description, "
            "scopes, is_system, created_at, updated_at) VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (role_code) DO UPDATE SET display_name = EXCLUDED.display_name, "
            "description = EXCLUDED.description, scopes = EXCLUDED.scopes, "
            "is_system = EXCLUDED.is_system, created_at = EXCLUDED.created_at, "
            "updated_at = EXCLUDED.updated_at",
            (
                key,
                value.get("name") or key,
                value.get("description") or "",
                value.get("scopes") or [],
                bool(value.get("system")),
                value.get("createdAt"),
                value.get("updatedAt"),
            ),
        )

    @staticmethod
    def _write_role(connection: Any, key: str, value: dict[str, Any]) -> None:
        connection.execute(
            "INSERT INTO public.account_role(id, account_id, programme_slug, role_code, "
            "jurisdiction_code, entity_type_code, scopes, created_at, valid_to) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET account_id = EXCLUDED.account_id, "
            "programme_slug = EXCLUDED.programme_slug, role_code = EXCLUDED.role_code, "
            "jurisdiction_code = EXCLUDED.jurisdiction_code, "
            "entity_type_code = EXCLUDED.entity_type_code, scopes = EXCLUDED.scopes, "
            "created_at = EXCLUDED.created_at, valid_to = EXCLUDED.valid_to",
            (
                key,
                value["accountId"],
                value.get("programmeSlug"),
                value.get("role"),
                value.get("jurisdiction"),
                value.get("entityType"),
                json.dumps(value.get("scopes") or []),
                value.get("createdAt"),
                value.get("validTo"),
            ),
        )

    @staticmethod
    def _write_session(
        connection: Any, key: str, value: dict[str, Any]
    ) -> None:
        connection.execute(
            "INSERT INTO public.auth_session(id, account_id, refresh_token_hash, access_jti, "
            "created_at, expires_at, revoked_at, user_agent, remote_addr) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET account_id = EXCLUDED.account_id, "
            "refresh_token_hash = EXCLUDED.refresh_token_hash, access_jti = EXCLUDED.access_jti, "
            "created_at = EXCLUDED.created_at, expires_at = EXCLUDED.expires_at, "
            "revoked_at = EXCLUDED.revoked_at, user_agent = EXCLUDED.user_agent, "
            "remote_addr = EXCLUDED.remote_addr",
            (
                key,
                value["accountId"],
                value["refreshHash"],
                value["accessJti"],
                value["createdAt"],
                value["expiresAt"],
                value.get("revokedAt"),
                value.get("userAgent"),
                value.get("remoteAddr"),
            ),
        )

    @staticmethod
    def _write_revocation(
        connection: Any, key: str, value: dict[str, Any]
    ) -> None:
        connection.execute(
            "INSERT INTO public.auth_revocation(jti, expires_at, revoked_at) "
            "VALUES (%s, to_timestamp(%s), now()) ON CONFLICT (jti) DO UPDATE "
            "SET expires_at = EXCLUDED.expires_at, revoked_at = now()",
            (key, value.get("expiresAt", 0)),
        )

    @staticmethod
    def _write_recovery(
        connection: Any, key: str, value: dict[str, Any]
    ) -> None:
        connection.execute(
            "INSERT INTO public.account_recovery_token(token_hash, account_id, expires_at, used_at) "
            "VALUES (%s, %s, %s, %s) ON CONFLICT (token_hash) DO UPDATE "
            "SET account_id = EXCLUDED.account_id, expires_at = EXCLUDED.expires_at, "
            "used_at = EXCLUDED.used_at",
            (key, value["accountId"], value["expiresAt"], value.get("usedAt")),
        )

    @staticmethod
    def _write_rate_limit(
        connection: Any, key: str, value: dict[str, Any]
    ) -> None:
        key_hash = (
            key if len(key) == 64 else hashlib.sha256(key.encode()).hexdigest()
        )
        connection.execute(
            "INSERT INTO public.identity_login_rate_limit(key_hash, window_started_at, "
            "request_count, expires_at, updated_at) "
            "VALUES (%s, to_timestamp(%s), %s, to_timestamp(%s), now()) "
            "ON CONFLICT (key_hash) DO UPDATE SET window_started_at = EXCLUDED.window_started_at, "
            "request_count = EXCLUDED.request_count, expires_at = EXCLUDED.expires_at, "
            "updated_at = now()",
            (
                key_hash,
                value.get("windowStart", 0),
                value.get("count", 0),
                value.get("expiresAt") or value.get("windowStart", 0) + 900,
            ),
        )

    @staticmethod
    def _write_evidence(
        connection: Any, key: str, value: dict[str, Any]
    ) -> None:
        connection.execute(
            "INSERT INTO public.callsign_evidence(id, callsign_id, submitted_by, evidence_type, "
            "source, checksum, metadata, status, submitted_at, reviewed_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET callsign_id = EXCLUDED.callsign_id, "
            "submitted_by = EXCLUDED.submitted_by, evidence_type = EXCLUDED.evidence_type, "
            "source = EXCLUDED.source, checksum = EXCLUDED.checksum, metadata = EXCLUDED.metadata, "
            "status = EXCLUDED.status, submitted_at = EXCLUDED.submitted_at, "
            "reviewed_at = EXCLUDED.reviewed_at",
            (
                key,
                value["callsignId"],
                value.get("accountId"),
                value.get("evidenceType"),
                value.get("source"),
                value.get("checksum"),
                json.dumps(value.get("metadata") or {}),
                value.get("status") or "PENDING",
                value.get("submittedAt"),
                value.get("reviewedAt"),
            ),
        )

    @staticmethod
    def _write_security_event(
        connection: Any, key: str, value: dict[str, Any]
    ) -> None:
        payload = value.get("payload") or {}
        account_id = payload.get("accountId")
        connection.execute(
            "INSERT INTO public.security_event(id, account_id, event_type, payload, occurred_at) "
            "VALUES (%s, %s, %s, %s::jsonb, %s) ON CONFLICT (id) DO UPDATE "
            "SET account_id = EXCLUDED.account_id, event_type = EXCLUDED.event_type, "
            "payload = EXCLUDED.payload, occurred_at = EXCLUDED.occurred_at",
            (
                key,
                account_id,
                value.get("eventType") or "identity.event",
                json.dumps(payload),
                value.get("occurredAt"),
            ),
        )

    @staticmethod
    def _write_oidc_mapping(
        connection: Any, key: str, value: dict[str, Any]
    ) -> None:
        connection.execute(
            "INSERT INTO public.identity_oidc_provider_mapping(id, programme_slug, issuer, "
            "client_id, scopes, enabled, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (id) DO UPDATE SET programme_slug = EXCLUDED.programme_slug, "
            "issuer = EXCLUDED.issuer, client_id = EXCLUDED.client_id, scopes = EXCLUDED.scopes, "
            "enabled = EXCLUDED.enabled, created_at = EXCLUDED.created_at, "
            "updated_at = EXCLUDED.updated_at",
            (
                key,
                value["programmeSlug"],
                value["issuer"],
                value["clientId"],
                value.get("scopes") or [],
                bool(value.get("enabled", True)),
                value.get("createdAt"),
                value.get("updatedAt"),
            ),
        )
