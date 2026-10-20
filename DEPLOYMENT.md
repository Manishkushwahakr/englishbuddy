# ImproBuddy deployment

The frontend is static HTML/CSS/JavaScript. The API and WebSocket signaling run
on Render; no frontend framework or build step is required.

## Render: FastAPI web service

Create a Python web service from this repository with:

- **Root Directory:** repository root
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- **Health Check Path:** `/health`

Render supplies `PORT`; do not hardcode a port or commit one in the service
configuration.

Create or attach a PostgreSQL database and set these service environment
variables in Render's dashboard:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | The database's internal PostgreSQL connection URL |
| `SECRET_KEY` | A newly generated, long, random signing key; keep it private |
| `FRONTEND_ORIGINS` | Exact Vercel origin(s), comma-separated, with no paths |

For `FRONTEND_ORIGINS`, include the production deployment origin, for example
`https://your-project.vercel.app`. Add a custom domain or a specific Vercel
preview origin only if that origin needs API access. Do not use `*`. The
backend defaults to the two local development ports only when this variable is
unset.

The app creates missing database tables during startup. Set a reachable
PostgreSQL `DATABASE_URL` before the service starts. Table creation is not a
database migration and will not update existing tables.

## Vercel: static frontend

Import this repository as a Vercel project and set:

- **Root Directory:** `frontend`
- **Framework Preset:** Other
- **Build Command:** leave empty
- **Output Directory:** `.`
- **Install Command:** leave empty

`frontend/config.js` is configured to use
`https://englishbuddy-gsgg.onrender.com` for non-local deployments. This URL is
public client-side configuration, not a secret. The local development default remains
`http://127.0.0.1:8000` when the frontend is served from `localhost` or
`127.0.0.1`. If the production URL is missing, the page reports a configuration
error instead of sending requests to localhost.

Because this frontend is plain static files, Vercel project environment
variables are not injected into its browser JavaScript. Configure the public
API URL in `frontend/config.js`; do not put secrets there.

After the Vercel domain is known, set the same exact origin in Render's
`FRONTEND_ORIGINS`, then redeploy/restart the Render service. A custom Vercel
domain must also be included if users will access the frontend through it.
If browser developer tools show `Failed to fetch`, check the preflight response:
the API returns `400 Disallowed CORS origin` when the page's exact origin is not
in `FRONTEND_ORIGINS`. The frontend displays its current page origin in its
network-error message to help configure the allowlist.

## Database and secrets

- Set `DATABASE_URL` and `SECRET_KEY` in the Render service dashboard; do not
  commit `.env`, database credentials, or JWT signing keys.
- The existing database layer expects a PostgreSQL URL compatible with
  SQLAlchemy/psycopg2. Use Render's internal database URL when the web service
  and database are in the same region.
- `SECRET_KEY` signs JWTs. Replacing it invalidates existing login tokens.
- The repository's `.gitignore` excludes `.env`.

## WebRTC and verification limits

The frontend currently configures Google's public STUN server only. There is
no TURN server or TURN credential configuration. STUN may work for many
networks, but restrictive NATs/firewalls can prevent peers from connecting;
reliable cross-network production calls generally need a TURN service and
short-lived credentials. Browser microphone access requires HTTPS, which
Vercel provides.

## Smoke checks after deployment

1. Open `https://englishbuddy-gsgg.onrender.com/health`; expect `{"status":"healthy"}`.
2. Open the Vercel URL and verify browser developer tools show successful API
   requests to the Render HTTPS origin (not localhost) and no CORS errors.
3. Register/log in, refresh the page, and log out.
4. Test matching and WebSocket signaling with two separate browser sessions.
5. Allow microphone access and verify actual two-way speech on the networks you
   intend to support. Synthetic media and signaling checks do not prove
   microphone-based audio; TURN may be required.
