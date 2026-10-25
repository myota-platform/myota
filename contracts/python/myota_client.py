"""Dependency-light typed client for the preferred v1 resource APIs.

This file is intentionally checked in so scripts and service smoke tests can
use the contract without installing an OpenAPI generator.  The method names
mirror the canonical operationIds in ``contracts/openapi.yaml``; ``request``
remains available for operations which are not wrapped yet.
"""

from dataclasses import dataclass
from typing import Any, Mapping
from urllib.request import Request, urlopen
import json
import uuid


@dataclass(frozen=True)
class ApiError(Exception):
    status: int
    body: dict[str, Any]


class MyOTAClient:
    def get_award_asset_content(self, asset_id: str) -> dict[str, Any]:
        return self.request("GET", f"/v1/awards/assets/{asset_id}/content")

    def put_award_asset_content(
        self, asset_id: str, content: bytes, media_type: str
    ) -> dict[str, Any]:
        return self.request(
            "PUT",
            f"/v1/awards/assets/{asset_id}/content",
            content,
            content_type=media_type,
        )

    def create_award_preview(self, body: dict[str, Any]) -> dict[str, Any]:
        return self.request("POST", "/v1/awards/previews", body)

    def __init__(
        self,
        base_url: str,
        timeout: float = 10,
        access_token: str | None = None,
    ) -> None:
        self.base_url, self.timeout, self.access_token = (
            base_url.rstrip("/"),
            timeout,
            access_token,
        )

    def request(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | bytes | None = None,
        idempotency_key: str | None = None,
        query: Mapping[str, Any] | None = None,
        expected_version: int | None = None,
        content_type: str = "application/json",
        accept: str = "application/json",
    ) -> dict[str, Any] | bytes:
        if query:
            from urllib.parse import urlencode

            path = f"{path}?{urlencode({key: value for key, value in query.items() if value is not None})}"
        payload = (
            body
            if isinstance(body, bytes)
            else None
            if body is None
            else json.dumps(body).encode()
        )
        headers = {
            "Accept": accept,
            "X-Request-ID": "client-generated",
        }
        if payload is not None:
            headers["Content-Type"] = content_type
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        if expected_version is not None:
            headers["If-Match"] = f'"{expected_version}"'
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        try:
            with urlopen(
                Request(
                    self.base_url + path,
                    data=payload,
                    headers=headers,
                    method=method,
                ),
                timeout=self.timeout,
            ) as response:
                response_body = response.read()
                if accept == "image/webp":
                    return response_body
                return json.loads(response_body or b"{}")
        except Exception as exc:
            if hasattr(exc, "read"):
                body_data = json.loads(exc.read() or b"{}")
                raise ApiError(exc.code, body_data) from exc
            raise

    def _write(
        self,
        method: str,
        path: str,
        body: dict[str, Any],
        *,
        idempotency_key: str | None = None,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        return self.request(
            method,
            path,
            body,
            idempotency_key or str(uuid.uuid4()),
            expected_version=expected_version,
        )

    # Programme resources
    def patch_programme(
        self, slug: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return self._write("PATCH", f"/v1/programmes/{slug}", body)

    def assign_programme_entity_category(
        self, slug: str, category_code: str
    ) -> dict[str, Any]:
        return self._write(
            "PUT", f"/v1/programmes/{slug}/entity-types/{category_code}", {}
        )

    def unassign_programme_entity_category(
        self, slug: str, category_code: str
    ) -> dict[str, Any]:
        return self._write(
            "DELETE", f"/v1/programmes/{slug}/entity-types/{category_code}", {}
        )

    def patch_programme_content(
        self, slug: str, content_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return self._write(
            "PATCH", f"/v1/programmes/{slug}/content/{content_id}", body
        )

    def patch_programme_policy_draft(
        self, slug: str, draft_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return self._write(
            "PATCH", f"/v1/programmes/{slug}/policy-drafts/{draft_id}", body
        )

    # Identity and geodata resources
    def patch_identity_account(
        self, account_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return self._write(
            "PATCH", f"/v1/identity/accounts/{account_id}", body
        )

    def patch_identity_profile(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._write("PATCH", "/v1/identity/me/profile", body)

    def get_identity_profile_image(self) -> bytes:
        result = self.request(
            "GET",
            "/v1/identity/me/profile-image",
            accept="image/webp",
        )
        return result if isinstance(result, bytes) else b""

    def put_identity_profile_image(
        self, content: bytes, media_type: str
    ) -> dict[str, Any]:
        result = self.request(
            "PUT",
            "/v1/identity/me/profile-image",
            content,
            content_type=media_type,
        )
        return result if isinstance(result, dict) else {}

    def delete_identity_profile_image(self) -> dict[str, Any]:
        result = self.request("DELETE", "/v1/identity/me/profile-image", {})
        return result if isinstance(result, dict) else {}

    def get_account_profile_image(self, account_id: str) -> bytes:
        result = self.request(
            "GET",
            f"/v1/identity/accounts/{account_id}/profile-image",
            accept="image/webp",
        )
        return result if isinstance(result, bytes) else b""

    def create_identity_role(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._write("POST", "/v1/identity/roles", body)

    def patch_identity_role(
        self, role_code: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return self._write("PATCH", f"/v1/identity/roles/{role_code}", body)

    def patch_geodata_entity_metadata(
        self,
        entity_id: str,
        body: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        return self._write(
            "PATCH",
            f"/v1/geodata/entities/{entity_id}",
            body,
            expected_version=expected_version,
        )

    def post_geodata_entity_location_enrichment_request(
        self,
        entity_id: str,
        body: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        return self._write(
            "POST",
            f"/v1/geodata/entities/{entity_id}/location-enrichment-requests",
            body,
            expected_version=expected_version,
        )

    def put_geodata_entity_geometry(
        self,
        entity_id: str,
        body: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        return self._write(
            "PUT",
            f"/v1/geodata/entities/{entity_id}/geometry",
            body,
            expected_version=expected_version,
        )

    def put_geodata_entity_categories(
        self,
        entity_id: str,
        body: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        return self._write(
            "PUT",
            f"/v1/geodata/entities/{entity_id}/categories",
            body,
            expected_version=expected_version,
        )

    def post_geodata_entity_review(
        self,
        entity_id: str,
        body: dict[str, Any],
        *,
        expected_version: int | None = None,
    ) -> dict[str, Any]:
        return self._write(
            "POST",
            f"/v1/geodata/entities/{entity_id}/reviews",
            body,
            expected_version=expected_version,
        )

    def post_geodata_proposal(self, body: dict[str, Any]) -> dict[str, Any]:
        return self._write("POST", "/v1/geodata/proposals", body)

    def create_geodata_entity_deletion_job(
        self, body: dict[str, Any]
    ) -> dict[str, Any]:
        return self._write("POST", "/v1/geodata/entity-deletion-jobs", body)

    def confirm_geodata_entity_deletion_job(
        self, job_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return self._write(
            "POST", f"/v1/geodata/entity-deletion-jobs/{job_id}/confirm", body
        )

    def patch_award(
        self, award_id: str, body: dict[str, Any]
    ) -> dict[str, Any]:
        return self._write("PATCH", f"/v1/awards/{award_id}", body)
