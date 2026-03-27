import os
from typing import Annotated

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.auth import get_user_id_from_payload, verify_supabase_jwt
from app.parsers import get_parser
from app.schemas import ParseResult

# Register parsers (side effects)
import app.parsers.generic_csv  # noqa: F401, E402
import app.parsers.generic_pdf  # noqa: F401, E402
import app.parsers.generic_xlsx  # noqa: F401, E402

PARSER_VERSION = os.environ.get("PARSER_VERSION", "0.1.0")

app = FastAPI(title="Finanzas statement parser", version=PARSER_VERSION)

_origins = os.environ.get("CORS_ALLOW_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

bearer = HTTPBearer(auto_error=False)


def require_user(creds: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]) -> str:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Missing bearer token")
    try:
        payload = verify_supabase_jwt(creds.credentials)
        return get_user_id_from_payload(payload)
    except Exception as e:
        raise HTTPException(status_code=401, detail=f"Invalid token: {e!s}") from e


@app.get("/health")
def health():
    return {"status": "ok", "parser_version": PARSER_VERSION}


_EXT_TO_TYPE = {".csv": "csv", ".xlsx": "xlsx", ".xlsm": "xlsx", ".pdf": "pdf"}


@app.post("/parse", response_model=ParseResult)
async def parse_statement(
    user_id: Annotated[str, Depends(require_user)],
    file: UploadFile = File(...),
    bank: str = Form(...),
    profile_id: Annotated[str | None, Form()] = None,
):
    _ = user_id  # available for logging / quotas
    _ = profile_id
    name = (file.filename or "").lower()
    ext = None
    for e in _EXT_TO_TYPE:
        if name.endswith(e):
            ext = e
            break
    if ext is None:
        raise HTTPException(status_code=400, detail="Unsupported file extension (use .csv, .xlsx, .pdf)")
    file_type = _EXT_TO_TYPE[ext]
    parser = get_parser(bank, file_type)
    if parser is None:
        raise HTTPException(status_code=400, detail=f"No parser for bank={bank!r} type={file_type!r}")

    raw = await file.read()
    if len(raw) > 15 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="File too large (max 15MB)")

    from io import BytesIO

    try:
        result = parser(BytesIO(raw), bank.strip().lower())
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"Parse failed: {e!s}") from e

    result.bank_code = bank.strip().lower()
    result.file_type = file_type
    return result
