import os
from typing import Any

import jwt


def verify_supabase_jwt(token: str) -> dict[str, Any]:
    secret = os.environ.get("SUPABASE_JWT_SECRET", "").strip()
    if not secret:
        raise RuntimeError("SUPABASE_JWT_SECRET is not set")
    # Supabase signs HS256 with the JWT secret from Project Settings → API
    return jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        audience=os.environ.get("SUPABASE_JWT_AUDIENCE", "authenticated"),
        options={"require": ["exp", "sub"]},
    )


def get_user_id_from_payload(payload: dict[str, Any]) -> str:
    sub = payload.get("sub")
    if not sub:
        raise jwt.InvalidTokenError("missing sub")
    return str(sub)
