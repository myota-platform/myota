from __future__ import annotations

import io
import os
import sys
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from unittest.mock import patch

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from identity import IdentityHandler, seed  # noqa: E402
from profile_images import (  # noqa: E402
    ProfileImageStore,
    normalize_profile_image,
)


def image_bytes(
    image_format: str = "PNG", size: tuple[int, int] = (800, 400)
) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, (20, 80, 140)).save(output, format=image_format)
    return output.getvalue()


def jpeg_with_exif() -> bytes:
    output = io.BytesIO()
    image = Image.new("RGB", (32, 16), (20, 80, 140))
    exif = Image.Exif()
    exif[270] = "Private source metadata"
    exif[274] = 6
    image.save(output, format="JPEG", exif=exif)
    return output.getvalue()


def animated_webp_bytes() -> bytes:
    output = io.BytesIO()
    first = Image.new("RGB", (8, 8), (20, 80, 140))
    second = Image.new("RGB", (8, 8), (80, 20, 140))
    first.save(
        output,
        format="WEBP",
        save_all=True,
        append_images=[second],
        duration=100,
        loop=0,
    )
    return output.getvalue()


class ProfileFieldsAndImagesTests(unittest.TestCase):
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
        self.user = {
            "id": "profile-user",
            "displayName": "Profile User",
            "email": "profile@example.test",
            "participationType": "SWL",
            "status": "ACTIVE",
            "callsigns": [],
            "primaryCallsignId": None,
        }
        IdentityHandler.store.items[self.user["id"]] = self.user

    def tearDown(self):
        IdentityHandler.store.items = self.previous_items
        IdentityHandler.store.events = self.previous_events
        IdentityHandler.store.data = self.previous_data
        IdentityHandler.store.idempotency = self.previous_idempotency

    @staticmethod
    def token(account):
        return IdentityHandler._mint_tokens(account, {})["accessToken"]

    def request(self, account, body=None, **extra):
        return {
            "Authorization": "Bearer " + self.token(account),
            "_http": "1",
            "_body": body or {},
            **extra,
        }

    def test_profile_fields_normalize_and_clear(self):
        params = self.request(
            self.user,
            {
                "websiteUrl": " HTTPS://example.test/about ",
                "biographyMarkdown": "**Hello**\n\n[Site](https://example.test)",
            },
        )
        result = IdentityHandler.update_own_profile(None, params)
        self.assertEqual(result["websiteUrl"], "https://example.test/about")
        self.assertEqual(
            result["biographyMarkdown"],
            "**Hello**\n\n[Site](https://example.test)",
        )
        cleared = IdentityHandler.update_own_profile(
            None,
            self.request(
                self.user,
                {"websiteUrl": "", "biographyMarkdown": None},
            ),
        )
        self.assertIsNone(cleared["websiteUrl"])
        self.assertIsNone(cleared["biographyMarkdown"])

    def test_profile_fields_reject_unsafe_or_oversized_values_atomically(self):
        cases = (
            {"websiteUrl": "javascript:alert(1)"},
            {"websiteUrl": "https://user:pass@example.test"},
            {"websiteUrl": "ftp://example.test"},
            {"websiteUrl": "https://example.test/" + "a" * 2048},
            {"biographyMarkdown": "x" * 2001},
            {"profileImage": {"id": "client-selected"}},
            {},
        )
        for body in cases:
            with self.subTest(body=list(body)):
                before = dict(self.user)
                with self.assertRaises(ValueError):
                    IdentityHandler.update_own_profile(
                        None, self.request(self.user, body)
                    )
                self.assertEqual(self.user, before)

    def test_admin_profile_validation_precedes_any_account_mutation(self):
        token = self.token(self.root)
        request = {
            "Authorization": "Bearer " + token,
            "_http": "1",
            "accountId": self.user["id"],
            "_body": {
                "displayName": "Must not partially apply",
                "websiteUrl": "javascript:bad()",
            },
        }
        with self.assertRaises(ValueError):
            IdentityHandler.update_admin_account(None, request)
        self.assertEqual(self.user["displayName"], "Profile User")

    def test_profile_image_is_normalized_and_metadata_is_not_exposed(self):
        normalized = normalize_profile_image(jpeg_with_exif(), "image/jpeg")
        with Image.open(io.BytesIO(normalized)) as output:
            self.assertEqual(output.format, "WEBP")
            self.assertEqual(output.size, (512, 512))
            self.assertFalse(output.getexif())
            self.assertNotIn("Private source metadata", output.info.values())

    def test_image_validation_rejects_mismatched_animated_and_oversized(self):
        with self.assertRaisesRegex(ValueError, "does not match"):
            normalize_profile_image(image_bytes(), "image/jpeg")
        with self.assertRaisesRegex(ValueError, "animated"):
            normalize_profile_image(animated_webp_bytes(), "image/webp")
        with self.assertRaisesRegex(ValueError, "dimensions"):
            normalize_profile_image(image_bytes(size=(4097, 1)), "image/png")
        with self.assertRaisesRegex(ValueError, "5 MiB"):
            normalize_profile_image(b"x" * (5 * 1024 * 1024 + 1), "image/png")

    def test_upload_and_delete_are_owner_scoped_and_remove_previous_objects(
        self,
    ):
        calls = []

        class FakeStore:
            def put(self, account_id, image_id, content):
                calls.append(("put", account_id, image_id, content))

            def delete(self, account_id, image_id):
                calls.append(("delete", account_id, image_id))

        old_image = {
            "id": "old-image",
            "contentType": "image/webp",
            "width": 512,
            "height": 512,
            "updatedAt": "2026-10-01T00:00:00Z",
        }
        self.user["profileImage"] = old_image
        with patch("identity.profile_image_store", FakeStore()):
            uploaded = IdentityHandler.upload_own_profile_image(
                None,
                self.request(
                    self.user,
                    _raw_body=image_bytes(),
                    **{"Content-Type": "image/png"},
                ),
            )
            self.assertEqual(
                uploaded["profileImage"]["contentType"], "image/webp"
            )
            self.assertNotIn("bucket", uploaded["profileImage"])
            self.assertNotIn("key", uploaded["profileImage"])
            self.assertEqual(calls[0][0], "put")
            self.assertEqual(
                calls[1], ("delete", self.user["id"], "old-image")
            )
            deleted = IdentityHandler.delete_own_profile_image(
                None, self.request(self.user)
            )
        self.assertIsNone(deleted["profileImage"])
        self.assertEqual(calls[-1][0], "delete")

    def test_read_is_private_and_admin_access_is_scoped(self):
        self.user["profileImage"] = {
            "id": "private-image",
            "contentType": "image/webp",
            "width": 512,
            "height": 512,
        }
        stranger = {
            **self.user,
            "id": "other-profile-user",
            "email": "other@example.test",
        }
        IdentityHandler.store.items[stranger["id"]] = stranger
        with self.assertRaises(PermissionError):
            IdentityHandler.read_account_profile_image(
                None,
                {
                    "Authorization": "Bearer " + self.token(stranger),
                    "accountId": self.user["id"],
                },
            )
        with patch("identity.profile_image_store.get", return_value=b"webp"):
            response = IdentityHandler.read_own_profile_image(
                None, self.request(self.user)
            )
        self.assertEqual(response.content_type, "image/webp")
        self.assertEqual(response.body, b"webp")

    def test_profile_store_uses_its_dedicated_secret(self):
        with patch.dict(
            os.environ,
            {
                "MYOTA_OBJECT_STORAGE_ACCESS_KEY": "shared-admin-access",
                "MYOTA_OBJECT_STORAGE_SECRET_KEY": "shared-admin-secret",
                "MYOTA_PROFILE_IMAGE_ACCESS_KEY": "profile-access",
                "MYOTA_PROFILE_IMAGE_SECRET_KEY": "profile-secret",
            },
        ):
            store = ProfileImageStore()
        self.assertEqual(store.access_key, "profile-access")
        self.assertEqual(store.secret_key, "profile-secret")

    def test_anonymized_deactivation_clears_profile_and_deletes_image(self):
        self.user.update(
            {
                "websiteUrl": "https://profile.example.test",
                "biographyMarkdown": "Personal details",
                "profileImage": {
                    "id": "image-to-remove",
                    "contentType": "image/webp",
                    "width": 512,
                    "height": 512,
                },
            }
        )
        with patch("identity.profile_image_store.delete") as delete:
            result = IdentityHandler.deactivate_account(
                None,
                {
                    **self.request(self.user),
                    "accountId": self.user["id"],
                },
            )
        self.assertEqual(result["status"], "DEACTIVATED")
        self.assertIsNone(result["websiteUrl"])
        self.assertIsNone(result["biographyMarkdown"])
        self.assertIsNone(result["profileImage"])
        delete.assert_called_once_with(self.user["id"], "image-to-remove")


class ProfileImageOrphanCleanupTests(unittest.TestCase):
    def test_orphan_sweep_uses_prefix_and_grace_period(self):
        cutoff_old = datetime.now(timezone.utc) - timedelta(days=2)
        cutoff_new = datetime.now(timezone.utc)

        class Paginator:
            def paginate(self, **kwargs):
                self.kwargs = kwargs
                return [
                    {
                        "Contents": [
                            {
                                "Key": "profiles/account/old.webp",
                                "LastModified": cutoff_old,
                            },
                            {
                                "Key": "profiles/account/new.webp",
                                "LastModified": cutoff_new,
                            },
                            {
                                "Key": "other-bucket/object.webp",
                                "LastModified": cutoff_old,
                            },
                            {"Key": "profiles/account/no-date.webp"},
                        ]
                    }
                ]

        class Client:
            def __init__(self):
                self.deleted = []

            def get_paginator(self, operation):
                self.operation = operation
                return Paginator()

            def delete_object(self, **kwargs):
                self.deleted.append(kwargs)

        client = Client()
        store = ProfileImageStore()
        store.bucket = "private-profile-bucket"
        with patch.object(store, "_s3", return_value=client):
            removed = store.delete_orphans({("account", "referenced")})
        self.assertEqual(removed, 1)
        self.assertEqual(
            client.deleted,
            [
                {
                    "Bucket": "private-profile-bucket",
                    "Key": "profiles/account/old.webp",
                }
            ],
        )


class ProfileImageHttpRouteTests(unittest.TestCase):
    def setUp(self):
        self.previous_items = IdentityHandler.store.items
        self.previous_events = IdentityHandler.store.events
        self.previous_data = IdentityHandler.store.data
        self.previous_idempotency = IdentityHandler.store.idempotency
        IdentityHandler.store.items = {
            "http-profile-user": {
                "id": "http-profile-user",
                "email": "http-profile@example.test",
                "displayName": "HTTP Profile User",
                "participationType": "SWL",
                "status": "ACTIVE",
                "callsigns": [],
                "primaryCallsignId": None,
                "profileImage": {
                    "id": "http-image",
                    "contentType": "image/webp",
                    "width": 512,
                    "height": 512,
                },
            }
        }
        IdentityHandler.store.events = []
        IdentityHandler.store.data = {}
        IdentityHandler.store.idempotency = {}
        self.account = IdentityHandler.store.items["http-profile-user"]
        self.token = IdentityHandler._mint_tokens(self.account, {})[
            "accessToken"
        ]
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), IdentityHandler)
        self.thread = threading.Thread(
            target=self.server.serve_forever, daemon=True
        )
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        IdentityHandler.store.items = self.previous_items
        IdentityHandler.store.events = self.previous_events
        IdentityHandler.store.data = self.previous_data
        IdentityHandler.store.idempotency = self.previous_idempotency

    def test_authenticated_image_read_is_binary_and_private(self):
        with patch("identity.profile_image_store.get", return_value=b"webp"):
            response = urlopen(
                Request(
                    f"{self.base_url}/v1/identity/me/profile-image",
                    headers={"Authorization": "Bearer " + self.token},
                )
            )
            with response:
                self.assertEqual(response.status, 200)
                self.assertEqual(
                    response.headers["Content-Type"], "image/webp"
                )
                self.assertEqual(
                    response.headers["Cache-Control"], "private, no-store"
                )
                self.assertEqual(response.read(), b"webp")

    def test_http_upload_limit_returns_413(self):
        connection = HTTPConnection(
            "127.0.0.1", self.server.server_port, timeout=5
        )
        try:
            connection.putrequest("PUT", "/v1/identity/me/profile-image")
            connection.putheader("Authorization", "Bearer " + self.token)
            connection.putheader("Content-Type", "image/png")
            connection.putheader("Content-Length", str(5 * 1024 * 1024 + 1))
            connection.endheaders()
            response = connection.getresponse()
            self.assertEqual(response.status, 413)
            response.read()
        finally:
            connection.close()


if __name__ == "__main__":
    unittest.main()
