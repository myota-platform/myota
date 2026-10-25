#!/usr/bin/env python3
"""Write a private SeaweedFS S3 config with Identity restricted to its bucket."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def config_from_environment() -> dict:
    bucket = os.environ.get(
        "MYOTA_PROFILE_IMAGE_BUCKET", "myota-user-profile-images"
    )
    admin_access = os.environ.get("MYOTA_OBJECT_STORAGE_ACCESS_KEY", "")
    admin_secret = os.environ.get("MYOTA_OBJECT_STORAGE_SECRET_KEY", "")
    profile_access = os.environ.get("MYOTA_PROFILE_IMAGE_ACCESS_KEY", "")
    profile_secret = os.environ.get("MYOTA_PROFILE_IMAGE_SECRET_KEY", "")
    if not all(
        (bucket, admin_access, admin_secret, profile_access, profile_secret)
    ):
        raise ValueError(
            "S3 bucket and both credential pairs must be configured"
        )
    if profile_access == admin_access or profile_secret == admin_secret:
        raise ValueError(
            "profile image credentials must be separate from admin credentials"
        )
    return {
        "identities": [
            {
                "name": "myota-storage-admin",
                "credentials": [
                    {"accessKey": admin_access, "secretKey": admin_secret}
                ],
                "actions": ["Admin", "Read", "List", "Tagging", "Write"],
            },
            {
                "name": "myota-identity-profile-images",
                "credentials": [
                    {"accessKey": profile_access, "secretKey": profile_secret}
                ],
                "actions": [
                    f"Read:{bucket}",
                    f"Write:{bucket}",
                    f"List:{bucket}",
                ],
            },
        ]
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    try:
        config = config_from_environment()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(
            args.output,
            os.O_WRONLY
            | os.O_CREAT
            | os.O_TRUNC
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            output.write(json.dumps(config, separators=(",", ":")) + "\n")
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
