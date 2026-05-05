"""
auth.py

Entra ID (Azure AD) bearer-token validation for the FastAPI layer.

Validates JWT tokens issued by Microsoft Entra ID against the promobot-api
app registration. Tokens are verified using Microsoft's JWKS endpoint
(public keys), so no client secret is needed on the API side.

Environment variables
---------------------
    ENTRA_TENANT_ID      Azure AD tenant ID
    ENTRA_API_CLIENT_ID  Application (client) ID of the promobot-api registration
    AUTH_ENABLED         Set to "false" to disable auth in dev (default: "true")
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache

import httpx
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

log = logging.getLogger(__name__)

_TENANT_ID = os.getenv("ENTRA_TENANT_ID", "")
_API_CLIENT_ID = os.getenv("ENTRA_API_CLIENT_ID", "")
_AUTH_ENABLED = os.getenv("AUTH_ENABLED", "true").lower() not in ("false", "0", "no")

_bearer_scheme = HTTPBearer(auto_error=_AUTH_ENABLED)

_JWKS_URL = (
    f"https://login.microsoftonline.com/{_TENANT_ID}/discovery/v2.0/keys"
    if _TENANT_ID else ""
)
_ISSUER = (
    f"https://sts.windows.net/{_TENANT_ID}/"
    if _TENANT_ID else ""
)


@lru_cache(maxsize=1)
def _get_signing_keys() -> dict[str, str]:
    """Fetch Microsoft's public signing keys (JWKS) and return {kid: pem} mapping.

    Cached for the process lifetime. If the key rotates, restart the service
    or clear this cache. In production, consider a TTL cache (e.g. 24h).
    """
    if not _JWKS_URL:
        return {}
    try:
        from jose.utils import base64url_decode
        from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicNumbers
        from cryptography.hazmat.backends import default_backend
        from cryptography.hazmat.primitives.serialization import (
            Encoding, PublicFormat,
        )
        import base64

        resp = httpx.get(_JWKS_URL, timeout=10)
        resp.raise_for_status()
        keys = {}
        for key_data in resp.json().get("keys", []):
            if key_data.get("kty") != "RSA":
                continue
            kid = key_data["kid"]
            n_bytes = base64url_decode(key_data["n"].encode())
            e_bytes = base64url_decode(key_data["e"].encode())
            n_int = int.from_bytes(n_bytes, "big")
            e_int = int.from_bytes(e_bytes, "big")
            pub_key = RSAPublicNumbers(e_int, n_int).public_key(default_backend())
            pem = pub_key.public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo).decode()
            keys[kid] = pem
        log.info("Loaded %d signing keys from JWKS endpoint", len(keys))
        return keys
    except Exception as exc:
        log.error("Failed to fetch JWKS: %s", exc)
        return {}


def _validate_token(token: str) -> dict:
    """Decode and validate a JWT token against Entra ID public keys."""
    from jose import jwt, JWTError

    signing_keys = _get_signing_keys()
    if not signing_keys:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth service unavailable — could not load signing keys",
        )

    unverified_header = jwt.get_unverified_header(token)
    kid = unverified_header.get("kid")
    if kid not in signing_keys:
        _get_signing_keys.cache_clear()
        signing_keys = _get_signing_keys()
        if kid not in signing_keys:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token signing key not recognized",
            )

    # python-jose only accepts a single string for audience.
    # Entra ID v1 tokens carry api://{client_id} as the audience,
    # v2 tokens carry just {client_id}. Try both.
    for aud in (f"api://{_API_CLIENT_ID}", _API_CLIENT_ID):
        try:
            payload = jwt.decode(
                token,
                signing_keys[kid],
                algorithms=["RS256"],
                audience=aud,
                issuer=_ISSUER,
                options={"verify_exp": True, "verify_aud": True, "verify_iss": True},
            )
            return payload
        except JWTError:
            continue

    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid token: audience mismatch",
    )


async def require_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> dict:
    """FastAPI dependency that validates the Bearer token.

    When AUTH_ENABLED=false, returns a stub payload for local development.
    """
    if not _AUTH_ENABLED:
        return {"sub": "dev-user", "name": "Dev User", "roles": []}

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header missing",
        )

    return _validate_token(credentials.credentials)
