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
| `FRONTEND_ORIGINS` | `https://englishbuddy-for-me.vercel.app` (plus any exact custom domain, comma-separated) |
| `MATCHING_FALLBACK_WAIT_SECONDS` | Optional; defaults to `9` before adjacent English levels can match |
| `MATCHING_REPEAT_COOLDOWN_SECONDS` | Optional; defaults to `600` seconds before recently paired users can match again if alternatives exist |

Each user may complete up to five successful partner skips in a rolling
30-minute window. The limit is enforced using existing matching queue history,
so it requires no database schema migration. A rejected or duplicate skip does
not consume a skip.

Set `FRONTEND_ORIGINS` to the exact production deployment origin
`https://englishbuddy-for-me.vercel.app`. Add a custom domain or a specific
Vercel preview origin only if that origin needs API access. Do not use `*`.
When this variable is unset, the backend allows this production origin and
the local development ports.

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

If Render already has a `FRONTEND_ORIGINS` environment variable, it overrides
the code defaults. Ensure its value includes
`https://englishbuddy-for-me.vercel.app` exactly (no trailing slash or path),
then redeploy/restart the Render service. A custom Vercel domain must also be
included if users will access the frontend through it.
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

### Transcription privacy and runtime

WebRTC voice remains peer-to-peer. The frontend separately sends bounded,
five-second mono PCM/WAV chunks over
`/ws/conversation/{conversation_id}/transcription`; the signaling socket remains
for WebRTC messages. The server verifies the JWT and active conversation
membership and derives the speaker ID from that JWT. It accepts at most 256 KiB
and eight seconds per chunk, and processes at most one Faster-Whisper chunk at
a time per backend process. Busy or malformed chunks are discarded rather than
queued.

Audio is held temporarily in process memory while Faster-Whisper runs. It is
not written to files, the database, logs, or an application queue/cache. The
speaker-labelled Faster-Whisper transcript is retained only in bounded process
memory (up to 720 chunks / 120,000 characters per conversation) and cleared
when the conversation ends, is skipped, or the signaling connection closes.
Process restarts also clear it. There is no transcript database retention or
LLM feedback in this phase. Keep the Render service at its default single
Uvicorn worker if relying on this in-memory session transcript; multiple
workers would maintain separate session memories.

The browser's Web Speech API transcript is rendered only in that participant's
page and is not sent to the other participant. Browser vendors may use remote
speech-recognition services; this application cannot guarantee that browser
transcription is processed locally. Users who require strictly local browser
recognition should disable this feature or use a browser that provides an
on-device recognition mode.

Microphone permission is requested only after the matched user selects
**Enable microphone and start audio**, keeping the permission prompt tied to a
clear user action. Browser speech recognition is also opt-in: after the audio
call connects, expand the transcript panel and select **Start live transcript**
so recognition starts from a user action. Support varies by browser and operating
system; the frontend detects the standard and WebKit-prefixed APIs and reports
when neither is available. Mobile browsers may suspend recognition when the page
is backgrounded or the device is locked. In that case, return to the call and
select **Resume live transcript**. Browser recognition failures do not stop
WebRTC or the independent Faster-Whisper audio-chunk path.

The Faster-Whisper `small` CPU/int8 model is loaded lazily on first
transcription, so the first chunk may take longer and the Render instance needs
sufficient CPU and memory. No new Python package is required for the
transcription transport.

## Smoke checks after deployment

1. Open `https://englishbuddy-gsgg.onrender.com/health`; expect `{"status":"healthy"}`.
2. Open the Vercel URL and verify browser developer tools show successful API
   requests to the Render HTTPS origin (not localhost) and no CORS errors.
3. Register/log in, refresh the page, and log out.
4. Test matching and WebSocket signaling with two separate browser sessions.
5. Allow microphone access and verify actual two-way speech on the networks you
   intend to support. Synthetic media and signaling checks do not prove
   microphone-based audio; TURN may be required.
