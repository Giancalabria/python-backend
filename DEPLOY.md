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

From the repository root, a `render.yaml` is provided. In Render: **New → Blueprint**, select the repo and apply. Set secret values when prompted (`SUPABASE_JWT_SECRET`, `CORS_ALLOW_ORIGINS`).

## Required environment variables

| Variable | Description |
|----------|-------------|
| `SUPABASE_JWT_SECRET` | Supabase → Project Settings → API → **JWT Secret** (not the anon key). |
| `SUPABASE_JWT_AUDIENCE` | Usually `authenticated`. |
| `CORS_ALLOW_ORIGINS` | Comma-separated browser origins, e.g. `https://your-app.vercel.app,http://localhost:5173` (no paths). |

Optional: `PARSER_VERSION` (e.g. `0.1.0`).

## Verify after deploy

Open `https://<your-service>.onrender.com/health` — you should see JSON like `{"status":"ok","parser_version":"..."}`.
