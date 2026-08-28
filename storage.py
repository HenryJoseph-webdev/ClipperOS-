"""Provider-neutral persistent media storage backed by Backblaze B2."""

from __future__ import annotations

import mimetypes
import os
from pathlib import Path
from typing import Any

from config import (
    B2_APPLICATION_KEY,
    B2_APPLICATION_KEY_ID,
    B2_BUCKET_NAME,
    B2_ENDPOINT,
    B2_REGION,
    B2_SIGNED_URL_TTL,
)


class StorageError(RuntimeError):
    """Raised when a persistent storage operation cannot be completed."""


class B2Storage:
    def __init__(self, client: Any = None):
        self.bucket = B2_BUCKET_NAME
        self.ttl = B2_SIGNED_URL_TTL
        self._client = client

    @property
    def configured(self) -> bool:
        return bool(
            self.bucket
            and B2_ENDPOINT
            and B2_REGION
            and B2_APPLICATION_KEY_ID
            and B2_APPLICATION_KEY
        )

    def _get_client(self):
        if self._client is not None:
            return self._client
        if not self.configured:
            raise StorageError("Persistent media storage is not configured.")
        try:
            import boto3

            self._client = boto3.client(
                "s3",
                endpoint_url=B2_ENDPOINT,
                aws_access_key_id=B2_APPLICATION_KEY_ID,
                aws_secret_access_key=B2_APPLICATION_KEY,
                region_name=B2_REGION,
            )
            return self._client
        except Exception as exc:
            raise StorageError(f"Could not initialize persistent media storage: {exc}") from exc

    @staticmethod
    def _content_type(filename: str) -> str:
        return mimetypes.guess_type(filename)[0] or "application/octet-stream"

    @staticmethod
    def _safe_download_name(filename: str) -> str:
        name = Path(filename).name or "download"
        return "".join(char if char not in '\"\\\r\n' else "_" for char in name)

    def upload_file(self, local_path: str, storage_key: str, filename: str) -> str:
        path = os.path.abspath(local_path)
        if not os.path.isfile(path):
            raise StorageError("The completed media file no longer exists locally.")
        try:
            self._get_client().upload_file(
                path,
                self.bucket,
                storage_key,
                ExtraArgs={"ContentType": self._content_type(filename)},
            )
        except Exception as exc:
            raise StorageError(f"Could not upload completed media: {exc}") from exc
        return storage_key

    def signed_download_url(self, storage_key: str, filename: str) -> str:
        if not storage_key:
            raise StorageError("The completed job has no persistent storage key.")
        try:
            return self._get_client().generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": storage_key,
                    "ResponseContentType": self._content_type(filename),
                    "ResponseContentDisposition": (
                        f'attachment; filename="{self._safe_download_name(filename)}"'
                    ),
                },
                ExpiresIn=self.ttl,
            )
        except Exception as exc:
            raise StorageError(f"Could not create a media download URL: {exc}") from exc


storage = B2Storage()
