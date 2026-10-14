"""Private SeaweedFS storage and normalization for Identity profile images."""

from __future__ import annotations

import io
import os
import warnings
from datetime import datetime, timedelta, timezone
from typing import Any

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PROFILE_IMAGE_BYTES = 5 * 1024 * 1024
MAX_PROFILE_IMAGE_DIMENSION = 4096
PROFILE_IMAGE_SIZE = (512, 512)
MAX_PROFILE_IMAGE_OUTPUT_BYTES = 256 * 1024
ORPHAN_GRACE_SECONDS = max(
    3600,
    int(os.environ.get("MYOTA_PROFILE_IMAGE_ORPHAN_GRACE_SECONDS", "86400")),
)
INPUT_FORMATS = {
    "image/jpeg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
}


def normalize_profile_image(content: bytes, content_type: str) -> bytes:
    """Validate, square-crop and re-encode an image without source metadata."""
    expected_format = INPUT_FORMATS.get(content_type.split(";", 1)[0].strip())
    if not expected_format:
        raise ValueError("profile image must be JPEG, PNG, or WebP")
    if not content or len(content) > MAX_PROFILE_IMAGE_BYTES:
        raise ValueError("profile image must be between 1 byte and 5 MiB")

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(content)) as source:
                if source.format != expected_format:
                    raise ValueError(
                        "profile image content does not match its media type"
                    )
                if (
                    getattr(source, "is_animated", False)
                    or getattr(source, "n_frames", 1) != 1
                ):
                    raise ValueError(
                        "animated profile images are not supported"
                    )
                width, height = source.size
                if (
                    width < 1
                    or height < 1
                    or width > MAX_PROFILE_IMAGE_DIMENSION
                    or height > MAX_PROFILE_IMAGE_DIMENSION
                ):
                    raise ValueError(
                        "profile image dimensions exceed 4096 pixels"
                    )
                source.verify()

            with Image.open(io.BytesIO(content)) as source:
                has_alpha = (
                    "A" in source.getbands() or "transparency" in source.info
                )
                mode = "RGBA" if has_alpha else "RGB"
                oriented = ImageOps.exif_transpose(source)
                normalized = ImageOps.fit(
                    oriented.convert(mode),
                    PROFILE_IMAGE_SIZE,
                    method=Image.Resampling.LANCZOS,
                    centering=(0.5, 0.5),
                )
                normalized.info.clear()
                output = io.BytesIO()
                for quality in (85, 75, 65, 55):
                    output.seek(0)
                    output.truncate(0)
                    normalized.save(
                        output,
                        format="WEBP",
                        quality=quality,
                        method=4,
                    )
                    if output.tell() <= MAX_PROFILE_IMAGE_OUTPUT_BYTES:
                        break
                if output.tell() > MAX_PROFILE_IMAGE_OUTPUT_BYTES:
                    raise ValueError(
                        "normalized profile image exceeds 256 KiB"
                    )
                return output.getvalue()
    except Image.DecompressionBombError as exc:
        raise ValueError("profile image dimensions are unsafe") from exc
    except Image.DecompressionBombWarning as exc:
        raise ValueError("profile image dimensions are unsafe") from exc
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("profile image is malformed or unsupported") from exc


class ProfileImageStore:
    """S3-compatible access to the private, deployment-provisioned bucket."""

    def __init__(self) -> None:
        self.endpoint = os.environ.get(
            "MYOTA_OBJECT_STORAGE_ENDPOINT", "http://seaweedfs:8333"
        )
        self.bucket = os.environ.get(
            "MYOTA_PROFILE_IMAGE_BUCKET", "myota-user-profile-images"
        )
        self.access_key = os.environ.get("MYOTA_PROFILE_IMAGE_ACCESS_KEY", "")
        self.secret_key = os.environ.get("MYOTA_PROFILE_IMAGE_SECRET_KEY", "")
        self.region = os.environ.get(
            "MYOTA_OBJECT_STORAGE_REGION", "us-east-1"
        )
        self._client: Any = None

    def _s3(self) -> Any:
        if self._client is not None:
            return self._client
        if not self.access_key or not self.secret_key:
            raise RuntimeError(
                "profile image storage credentials are unavailable"
            )
        try:
            import boto3
            from botocore.client import Config
        except ImportError as exc:  # pragma: no cover - image ships boto3
            raise RuntimeError(
                "profile image storage client is unavailable"
            ) from exc
        self._client = boto3.client(
            "s3",
            endpoint_url=self.endpoint,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
            ),
        )
        return self._client

    @staticmethod
    def _key(account_id: str, image_id: str) -> str:
        return f"profiles/{account_id}/{image_id}.webp"

    def put(self, account_id: str, image_id: str, content: bytes) -> None:
        self._s3().put_object(
            Bucket=self.bucket,
            Key=self._key(account_id, image_id),
            Body=content,
            ContentType="image/webp",
            CacheControl="private, no-store",
        )

    def get(self, account_id: str, image_id: str) -> bytes:
        response = self._s3().get_object(
            Bucket=self.bucket,
            Key=self._key(account_id, image_id),
        )
        body = response["Body"]
        try:
            return body.read(MAX_PROFILE_IMAGE_OUTPUT_BYTES + 1)
        finally:
            body.close()

    def delete(self, account_id: str, image_id: str) -> None:
        self._s3().delete_object(
            Bucket=self.bucket,
            Key=self._key(account_id, image_id),
        )

    def delete_orphans(self, referenced: set[tuple[str, str]]) -> int:
        """Remove old bucket objects not referenced by persisted Identity state."""
        client = self._s3()
        removed = 0
        cutoff = datetime.now(timezone.utc) - timedelta(
            seconds=ORPHAN_GRACE_SECONDS
        )
        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix="profiles/"):
            for item in page.get("Contents", []):
                key = item.get("Key", "")
                parts = key.split("/")
                if (
                    len(parts) != 3
                    or parts[0] != "profiles"
                    or not parts[2].endswith(".webp")
                    or not isinstance(item.get("LastModified"), datetime)
                    or item["LastModified"] > cutoff
                ):
                    continue
                reference = (parts[1], parts[2][:-5])
                if reference in referenced:
                    continue
                client.delete_object(Bucket=self.bucket, Key=key)
                removed += 1
        return removed


profile_image_store = ProfileImageStore()
