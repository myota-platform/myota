from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import yaml


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "render_seaweedfs_s3_config",
    ROOT / "scripts" / "render_seaweedfs_s3_config.py",
)
render_config = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render_config)


class ProfileImageStorageTests(unittest.TestCase):
    def setUp(self):
        self.credentials = patch.dict(
            os.environ,
            {
                "MYOTA_OBJECT_STORAGE_ACCESS_KEY": "admin-access-test",
                "MYOTA_OBJECT_STORAGE_SECRET_KEY": "admin-secret-test",
                "MYOTA_PROFILE_IMAGE_ACCESS_KEY": "profile-access-test",
                "MYOTA_PROFILE_IMAGE_SECRET_KEY": "profile-secret-test",
                "MYOTA_PROFILE_IMAGE_BUCKET": "myota-user-profile-images",
            },
            clear=False,
        )
        self.credentials.start()
        self.addCleanup(self.credentials.stop)

    def test_s3_config_scopes_identity_to_private_profile_bucket(self):
        config = render_config.config_from_environment()
        identities = {entry["name"]: entry for entry in config["identities"]}
        self.assertEqual(
            identities["myota-identity-profile-images"]["actions"],
            [
                "Read:myota-user-profile-images",
                "Write:myota-user-profile-images",
                "List:myota-user-profile-images",
            ],
        )
        self.assertEqual(
            identities["myota-storage-admin"]["actions"],
            ["Admin", "Read", "List", "Tagging", "Write"],
        )
        self.assertNotIn("anonymous", identities)

    def test_s3_config_file_is_private_and_never_prints_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "s3.json"
            stdout = io.StringIO()
            with (
                patch.object(
                    sys,
                    "argv",
                    ["render_seaweedfs_s3_config.py", "--output", str(output)],
                ),
                redirect_stdout(stdout),
            ):
                self.assertEqual(render_config.main(), 0)
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
            serialized = output.read_text(encoding="utf-8")
            self.assertIn("profile-access-test", serialized)
            self.assertEqual(stdout.getvalue(), "")
            self.assertNotIn("profile-access-test", stdout.getvalue())

    def test_private_config_can_be_owned_by_the_pinned_seaweed_runtime_user(
        self,
    ):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "s3.json"
            with (
                patch.object(
                    sys,
                    "argv",
                    [
                        "render_seaweedfs_s3_config.py",
                        "--output",
                        str(output),
                        "--owner-uid",
                        "1000",
                        "--owner-gid",
                        "1000",
                    ],
                ),
                patch.object(render_config.os, "fchown") as chown,
            ):
                self.assertEqual(render_config.main(), 0)
            self.assertEqual(chown.call_args.args[1:], (1000, 1000))
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)
        compose = yaml.safe_load((ROOT / "compose.yaml").read_text())
        self.assertEqual(
            compose["services"]["profile-image-s3-config-init"]["command"][
                -4:
            ],
            ["--owner-uid", "1000", "--owner-gid", "1000"],
        )

    def test_profile_identity_cannot_reuse_storage_admin_credentials(self):
        with patch.dict(
            os.environ,
            {
                "MYOTA_PROFILE_IMAGE_ACCESS_KEY": "admin-access-test",
                "MYOTA_PROFILE_IMAGE_SECRET_KEY": "admin-secret-test",
            },
        ):
            with self.assertRaisesRegex(ValueError, "must be separate"):
                render_config.config_from_environment()

    def test_deploy_runtime_uses_dedicated_identity_credentials(self):
        deployment = (ROOT / "helm/myota/templates/deployment.yaml").read_text(
            encoding="utf-8"
        )
        maintenance = (
            ROOT / "helm/myota/templates/identity-maintenance.yaml"
        ).read_text(encoding="utf-8")
        seaweed = (ROOT / "helm/myota/templates/seaweedfs.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("MYOTA_PROFILE_IMAGE_ACCESS_KEY", deployment)
        self.assertIn("MYOTA_PROFILE_IMAGE_SECRET_KEY", deployment)
        self.assertIn("profileImageExistingSecret", deployment)
        self.assertIn("profileImageExistingSecret", maintenance)
        self.assertIn("-s3.config=/etc/seaweedfs-auth/", seaweed)
        self.assertIn("s3ConfigSecret", seaweed)

    def test_compose_uses_private_bucket_and_scoped_s3_config(self):
        compose = yaml.safe_load(
            (ROOT / "compose.yaml").read_text(encoding="utf-8")
        )
        image_compose = yaml.safe_load(
            (ROOT / "compose.images.yaml").read_text(encoding="utf-8")
        )
        services = compose["services"]
        identity = services["identity"]
        maintenance = services["identity-maintenance"]
        seaweed = services["seaweedfs"]
        init = services["profile-image-s3-config-init"]
        self.assertIn(
            "MYOTA_PROFILE_IMAGE_ACCESS_KEY", identity["environment"]
        )
        self.assertNotIn(
            "MYOTA_OBJECT_STORAGE_ACCESS_KEY", identity["environment"]
        )
        self.assertIn("profile-image-bucket-init", identity["depends_on"])
        self.assertIn(
            "MYOTA_PROFILE_IMAGE_ACCESS_KEY", maintenance["environment"]
        )
        self.assertIn(
            "-s3.config=/etc/seaweedfs-auth/s3.json", seaweed["command"]
        )
        self.assertIn(
            "seaweedfs-s3-config:/etc/seaweedfs-auth:ro", seaweed["volumes"]
        )
        self.assertEqual(init["network_mode"], "none")
        self.assertIn("profile-image-s3-config-init", services)
        self.assertIn(
            "profile-image-bucket-init",
            image_compose["services"]["identity"]["depends_on"],
        )
        self.assertIn(
            "MYOTA_PROFILE_IMAGE_ACCESS_KEY",
            image_compose["services"]["identity"]["environment"],
        )

    def test_testing_profile_bucket_matches_its_scoped_identity(self):
        testing_values = yaml.safe_load(
            (ROOT / "helm/myota-test/values-testing.yaml").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(
            testing_values["myota"]["objectStorage"]["profileImageBucket"],
            "myota-test-user-profile-images",
        )
        self.assertEqual(
            testing_values["myota"]["objectStorage"][
                "profileImageExistingSecret"
            ],
            "myota-test-profile-image-s3-auth",
        )


if __name__ == "__main__":
    unittest.main()
