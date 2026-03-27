import os
from typing import Any

import jwt
from jwt import PyJWKClient

# Cache JWKS clients per project URL (avoids refetching keys every request)
_jwks_clients: dict[str, PyJWKClient] = {}


def _audience() -> str:
    return os.environ.get("SUPABASE_JWT_AUDIENCE", "authenticated")


def _issuer_from_supabase_url() -> str:
    base = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
    if not base:
        return ""
    return f"{base}/auth/v1"


def _jwks_client(base: str) -> PyJWKClient:
    jwks_url = f"{base.rstrip('/')}/auth/v1/.well-known/jwks.json"
    if jwks_url not in _jwks_clients:
        _jwks_clients[jwks_url] = PyJWKClient(jwks_url)
    return _jwks_clients[jwks_url]


def verify_supabase_jwt(token: str) -> dict[str, Any]:
    """
    Supabase may sign access tokens with:
    - HS256 + Legacy JWT Secret (older), or
    - ES256 / RS256 + JWKS (current ECC / rotation).

    We pick the path from the token header's `alg`.
    """
    audience = _audience()
    header = jwt.get_unverified_header(token)
    alg = (header.get("alg") or "").upper()

    decode_opts = {"require": ["exp", "sub"]}

    if alg == "HS256":
        secret = os.environ.get("SUPABASE_JWT_SECRET", "").strip()
        if not secret:
            raise RuntimeError(
                "This token is signed with HS256, but SUPABASE_JWT_SECRET is not set. "
                "Either set the Legacy JWT Secret on the server, or set SUPABASE_URL so ES256 "
                "tokens can be verified via JWKS."
            )
        return jwt.decode(
            token,
            secret,
            algorithms=["HS256"],
            audience=audience,
            options=decode_opts,
        )

    if alg in ("ES256", "RS256"):
        base = os.environ.get("SUPABASE_URL", "").strip().rstrip("/")
        if not base:
            raise RuntimeError(
                f"This token uses {alg}. Set SUPABASE_URL on the server to the same value as "
                "VITE_SUPABASE_URL (e.g. https://YOUR_PROJECT.supabase.co) so JWKS verification works."
            )
        iss = _issuer_from_supabase_url()
        client = _jwks_client(base)
        signing_key = client.get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=[alg],
            audience=audience,
            issuer=iss,
            options=decode_opts,
        )

    raise jwt.InvalidTokenError(f"Unsupported JWT alg: {alg!r} (expected HS256, ES256, or RS256)")


def get_user_id_from_payload(payload: dict[str, Any]) -> str:
    sub = payload.get("sub")
    if not sub:
        raise jwt.InvalidTokenError("missing sub")
    return str(sub)
