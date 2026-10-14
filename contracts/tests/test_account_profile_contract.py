from __future__ import annotations

import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker
import yaml


ROOT = Path(__file__).resolve().parents[1]


def openapi_document():
    return yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))


class AccountProfileContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.document = openapi_document()
        cls.schemas = cls.document["components"]["schemas"]

    def test_profile_update_bounds_and_allowed_properties(self):
        schema = self.schemas["AccountProfileUpdate"]
        validator = Draft202012Validator(
            schema, format_checker=FormatChecker()
        )
        for fixture in (
            {"websiteUrl": "https://example.test/profile"},
            {"websiteUrl": "HTTPS://example.test/profile"},
            {"websiteUrl": None, "biographyMarkdown": "Hello **world**"},
            {"biographyMarkdown": "x" * 2000},
        ):
            with self.subTest(fixture=list(fixture)):
                self.assertTrue(validator.is_valid(fixture))
        for fixture in (
            {},
            {"websiteUrl": "javascript:alert(1)"},
            {"websiteUrl": "ftp://example.test"},
            {"websiteUrl": "https://example.test/" + "x" * 2048},
            {"biographyMarkdown": "x" * 2001},
            {"profileImage": {"id": "caller-selected"}},
        ):
            with self.subTest(fixture=list(fixture)):
                self.assertFalse(validator.is_valid(fixture))

    def test_image_metadata_is_opaque_and_server_managed(self):
        schema = self.schemas["ProfileImageMetadata"]
        validator = Draft202012Validator(
            schema, format_checker=FormatChecker()
        )
        self.assertTrue(
            validator.is_valid(
                {
                    "id": "7f64b467-0b21-4bb1-8d5f-12c53e54615d",
                    "contentType": "image/webp",
                    "width": 512,
                    "height": 512,
                    "updatedAt": "2026-10-10T10:00:00Z",
                }
            )
        )
        self.assertFalse(
            validator.is_valid(
                {
                    "id": "7f64b467-0b21-4bb1-8d5f-12c53e54615d",
                    "contentType": "image/png",
                    "width": 512,
                    "height": 512,
                    "updatedAt": "2026-10-10T10:00:00Z",
                    "bucket": "private-bucket",
                }
            )
        )
        account = self.schemas["Account"]["properties"]
        self.assertEqual(account["websiteUrl"]["maxLength"], 2048)
        self.assertEqual(account["biographyMarkdown"]["maxLength"], 2000)

    def test_profile_image_routes_require_authentication_and_proxy_bytes(self):
        paths = self.document["paths"]
        protected = (
            ("/v1/identity/me/profile", "patch"),
            ("/v1/identity/me/profile-image", "get"),
            ("/v1/identity/me/profile-image", "put"),
            ("/v1/identity/me/profile-image", "delete"),
            ("/v1/identity/accounts/{accountId}/profile-image", "get"),
        )
        for path, method in protected:
            with self.subTest(path=path, method=method):
                operation = paths[path][method]
                self.assertIn("bearerAuth", operation["security"][0])
        upload = paths["/v1/identity/me/profile-image"]["put"]
        self.assertEqual(
            set(upload["requestBody"]["content"]),
            {"image/jpeg", "image/png", "image/webp"},
        )
        self.assertIn("5 MiB", upload["description"])
        self.assertIn(
            "private, no-store",
            paths["/v1/identity/me/profile-image"]["get"]["description"],
        )


if __name__ == "__main__":
    unittest.main()
