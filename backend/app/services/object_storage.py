from __future__ import annotations

import asyncio
from pathlib import Path, PurePosixPath
from urllib.parse import quote

import httpx

from app.config import Settings
from app.errors import APIError


class ObjectStorage:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def remote(self) -> bool:
        return bool(self.settings.supabase_url and self.settings.supabase_secret_key)

    @staticmethod
    def _validate_key(key: str) -> str:
        path = PurePosixPath(key)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise APIError(
                "INVALID_OBJECT_KEY", "The storage object key is invalid.", status_code=422
            )
        return path.as_posix()

    def local_path(self, bucket: str, key: str) -> Path:
        safe_key = self._validate_key(key)
        root = Path(self.settings.local_storage_path).resolve()
        target = (root / bucket / safe_key).resolve()
        if root not in target.parents:
            raise APIError(
                "INVALID_OBJECT_KEY", "The storage object key is invalid.", status_code=422
            )
        return target

    async def ensure_private_buckets(self) -> None:
        if not self.remote:
            return
        headers = {
            "Authorization": f"Bearer {self.settings.supabase_secret_key}",
            "apikey": self.settings.supabase_secret_key,
            "Content-Type": "application/json",
        }
        definitions = (
            (
                self.settings.sample_evidence_bucket,
                ["image/jpeg", "image/png", "image/webp"],
                8 * 1024 * 1024,
            ),
            (
                self.settings.response_evidence_bucket,
                ["image/jpeg", "image/png", "image/webp"],
                8 * 1024 * 1024,
            ),
            (
                self.settings.reports_bucket,
                ["application/pdf", "application/json"],
                20 * 1024 * 1024,
            ),
        )
        async with httpx.AsyncClient(timeout=15) as client:
            for bucket, mime_types, size_limit in definitions:
                response = await client.post(
                    f"{self.settings.supabase_url.rstrip('/')}/storage/v1/bucket",
                    headers=headers,
                    json={
                        "id": bucket,
                        "name": bucket,
                        "public": False,
                        "file_size_limit": size_limit,
                        "allowed_mime_types": mime_types,
                    },
                )
                if response.status_code not in {200, 201, 409}:
                    raise APIError(
                        "STORAGE_SETUP_FAILED",
                        "Private storage buckets could not be prepared.",
                        status_code=502,
                        details={"provider_status": response.status_code},
                    )

    async def put(self, bucket: str, key: str, payload: bytes, content_type: str) -> None:
        safe_key = self._validate_key(key)
        if not self.remote:
            target = self.local_path(bucket, safe_key)
            await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
            await asyncio.to_thread(target.write_bytes, payload)
            return
        encoded = quote(safe_key, safe="/")
        url = f"{self.settings.supabase_url.rstrip('/')}/storage/v1/object/{bucket}/{encoded}"
        headers = {
            "Authorization": f"Bearer {self.settings.supabase_secret_key}",
            "apikey": self.settings.supabase_secret_key,
            "Content-Type": content_type,
            "x-upsert": "false",
        }
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(url, headers=headers, content=payload)
        if response.status_code not in {200, 201}:
            raise APIError(
                "STORAGE_UPLOAD_FAILED",
                "The private object could not be stored.",
                status_code=502,
                details={"provider_status": response.status_code},
            )

    async def signed_url(self, bucket: str, key: str, *, download: bool = True) -> str | None:
        safe_key = self._validate_key(key)
        if not self.remote:
            return None
        encoded = quote(safe_key, safe="/")
        url = f"{self.settings.supabase_url.rstrip('/')}/storage/v1/object/sign/{bucket}/{encoded}"
        headers = {
            "Authorization": f"Bearer {self.settings.supabase_secret_key}",
            "apikey": self.settings.supabase_secret_key,
        }
        body = {"expiresIn": self.settings.signed_url_ttl_seconds, "download": download}
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(url, headers=headers, json=body)
        if response.status_code not in {200, 201}:
            raise APIError(
                "STORAGE_SIGNING_FAILED",
                "A temporary download link could not be created.",
                status_code=502,
            )
        value = response.json().get("signedURL") or response.json().get("signedUrl")
        if not value:
            raise APIError(
                "STORAGE_SIGNING_FAILED", "The storage provider returned no URL.", status_code=502
            )
        if str(value).startswith("http"):
            return str(value)
        return f"{self.settings.supabase_url.rstrip('/')}{value}"
