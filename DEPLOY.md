# Deploy this API on Render

Render’s **default Python** template assumes **Django** and runs `gunicorn your_application.wsgi`. This project is **FastAPI** and must run **Uvicorn**. If you leave the default start command, the deploy will fail with `gunicorn: command not found`.

## Option 1 — Docker (recommended)

1. In Render: **New → Web Service**, connect this Git repository.
2. **Runtime:** choose **Docker** (not “Python 3”).
3. If the repo root contains both `frontend/` and `parser-api/`:
   - **Dockerfile path:** `parser-api/Dockerfile`
   - **Docker build context:** `parser-api`
4. Clear **Start Command** (empty) so Render uses the `CMD` from the Dockerfile.
5. **Health check path:** `/health`
6. **Environment variables** (see below), then deploy.

## Option 2 — Native Python (no Docker)

1. **Root directory:** `parser-api`
2. **Build command:** `pip install -r requirements.txt`
3. **Start command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`  
   **Do not** use `gunicorn your_application.wsgi`.
4. **Health check path:** `/health`
5. **Environment variables** (see below), then deploy.

## Option 3 — Blueprint

From the repository root, a `render.yaml` is provided. In Render: **New → Blueprint**, select the repo and apply. Set secret values when prompted.

## Environment variables

| Variable | Required? | Description |
|----------|-------------|-------------|
| **`SUPABASE_URL`** | **Yes** (for current Supabase) | Same as the frontend: `https://YOUR_PROJECT_REF.supabase.co` (no trailing slash). Used to load **JWKS** and verify **ES256** (ECC) access tokens. |
| **`SUPABASE_JWT_SECRET`** | Optional | Only if tokens are still **HS256** (Legacy JWT Secret). New Supabase projects often use **ECC / ES256** only — then you **do not** rely on this for verification; **`SUPABASE_URL` is enough**. |
| **`SUPABASE_JWT_AUDIENCE`** | Optional | Default `authenticated`. |
| **`CORS_ALLOW_ORIGINS`** | Yes | Comma-separated **origins** (scheme + host, no path). Example: `http://localhost:5173,https://my-app.vercel.app`. Trailing slashes on hosts are normalized. |

Optional: `PARSER_VERSION` (e.g. `0.1.0`).

### JWT errors

- **`The specified alg value is not allowed`** — Your token is **ES256**, but the server only tried **HS256**. Fix: set **`SUPABASE_URL`** on Render and redeploy (this repo verifies ES256 via JWKS automatically).
- **`Invalid issuer`** — `SUPABASE_URL` must match the project that issued the token (same ref as in the frontend).

## Verify after deploy

Open `https://<your-service>.onrender.com/health` — you should see JSON like `{"status":"ok","parser_version":"..."}`.
