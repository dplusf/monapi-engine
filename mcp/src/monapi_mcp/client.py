"""HTTP client for a monapi engine instance.

One shared client for every tool: auth, timeouts, rate-limit backoff and
error translation live here, not in the tools. Errors are raised as
:class:`MonapiError` with a message that tells the caller what to do next
— agents act on those sentences, so they are part of the interface.
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

import httpx

DEFAULT_BASE_URL = "https://api.monapi.io"
DEFAULT_TIMEOUT = 10.0
# The engine's default email limit is 10/minute, so a 429 on a batch is
# expected, not exceptional. Wait and retry rather than failing the run.
MAX_RETRIES = 3


class MonapiError(RuntimeError):
    """An error worth showing to the model, phrased as a next step."""


@dataclass
class EngineConfig:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    profile: str = "default"
    timeout: float = DEFAULT_TIMEOUT

    @classmethod
    def from_env(cls) -> "EngineConfig":
        return cls(
            base_url=os.getenv("MONAPI_URL", DEFAULT_BASE_URL).rstrip("/"),
            api_key=os.getenv("MONAPI_API_KEY", ""),
            profile=os.getenv("MONAPI_PROFILE", "default"),
            timeout=float(os.getenv("MONAPI_TIMEOUT", DEFAULT_TIMEOUT)),
        )


class MonapiClient:
    """Async client against one engine instance.

    The httpx client is created lazily and reused, so a batch of checks
    shares connections instead of opening one per address.
    """

    def __init__(self, config: EngineConfig):
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._catalogue: dict[str, Any] | None = None

    async def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.config.base_url,
                headers={"X-API-Key": self.config.api_key},
                timeout=self.config.timeout,
                follow_redirects=True,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """GET with rate-limit backoff. Raises MonapiError on failure."""
        if not self.config.api_key:
            raise MonapiError(
                "No API key configured. Set MONAPI_API_KEY in the MCP server's "
                "environment — on a self-hosted engine it is one of the values "
                "in BOOTSTRAP_API_KEYS."
            )

        client = await self._http()
        delay = 2.0
        last_429: httpx.Response | None = None

        for attempt in range(MAX_RETRIES):
            try:
                response = await client.get(path, params=params)
            except httpx.TimeoutException as exc:
                raise MonapiError(
                    f"Engine at {self.config.base_url} did not answer within "
                    f"{self.config.timeout:g}s. Check that it is reachable, or raise "
                    "MONAPI_TIMEOUT."
                ) from exc
            except httpx.HTTPError as exc:
                raise MonapiError(
                    f"Cannot reach the engine at {self.config.base_url}: {exc}. "
                    "Check MONAPI_URL."
                ) from exc

            if response.status_code == 429:
                last_429 = response
                if attempt < MAX_RETRIES - 1:
                    wait = float(response.headers.get("Retry-After") or delay)
                    await asyncio.sleep(min(wait, 60.0))
                    delay *= 2
                    continue
                break

            return self._parse(response)

        raise MonapiError(
            "Rate limit exceeded and still limited after "
            f"{MAX_RETRIES} attempts (last status {last_429.status_code if last_429 else 429}). "
            "The engine's email check defaults to 10 requests per minute — check fewer "
            "addresses at once, or raise RATE_LIMIT_EMAIL on the engine."
        )

    @staticmethod
    def _parse(response: httpx.Response) -> dict[str, Any]:
        if response.status_code == 401:
            raise MonapiError(
                "Engine rejected the request: no API key was sent. Set MONAPI_API_KEY."
            )
        if response.status_code == 403:
            raise MonapiError(
                "Engine rejected the API key. Verify MONAPI_API_KEY matches a key "
                "known to this instance (BOOTSTRAP_API_KEYS)."
            )
        if response.status_code == 400:
            detail: Any = {}
            try:
                detail = response.json().get("detail", {})
            except ValueError:
                pass
            if isinstance(detail, dict) and detail.get("error") == "unknown_profile":
                available = ", ".join(detail.get("available", []))
                raise MonapiError(
                    f"Unknown policy profile. This instance offers: {available}. "
                    "Use monapi_list_profiles to see what each one does."
                )
            raise MonapiError(f"Engine rejected the request: {detail or response.text}")
        if response.status_code == 404:
            raise MonapiError(
                f"Endpoint {response.request.url.path} does not exist on this engine. "
                "It predates this MCP server — update the engine."
            )
        if response.status_code >= 500:
            raise MonapiError(
                f"Engine returned {response.status_code}. It is up but failing; "
                "check its logs."
            )

        try:
            return response.json()
        except ValueError as exc:
            raise MonapiError(
                f"Engine returned a non-JSON response ({response.status_code}). "
                "Is MONAPI_URL pointing at the API and not at the website?"
            ) from exc

    # -- checks ----------------------------------------------------------

    async def check(self, kind: str, value: str, profile: str | None = None) -> dict[str, Any]:
        """Run one check. `kind` is ip, domain or email."""
        return await self.get(
            f"/v1/check/{kind}/{quote(value, safe='')}",
            params={"profile": profile or self.config.profile},
        )

    async def profiles(self) -> dict[str, Any]:
        return await self.get("/v1/profiles")

    async def catalogue(self) -> dict[str, Any]:
        """The signal catalogue, fetched once and kept for the process.

        It only changes when the engine is redeployed, and explain calls
        would otherwise refetch it for every signal id.
        """
        if self._catalogue is None:
            self._catalogue = await self.get("/v1/signals")
        return self._catalogue

    async def explain(self, signal_id: str) -> dict[str, Any] | None:
        """Look up one concrete signal id in the catalogue."""
        catalogue = await self.catalogue()
        for entry in catalogue.get("signals", []):
            if entry.get("id") == signal_id:
                return entry

        best: dict[str, Any] | None = None
        best_len = -1
        for entry in catalogue.get("signals", []):
            pattern = entry.get("id_pattern")
            if not pattern:
                continue
            prefix = pattern.split("<", 1)[0]
            if prefix and signal_id.startswith(prefix) and len(prefix) > best_len:
                best, best_len = entry, len(prefix)
        return best
