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
| `GEMINI_API_KEY` | Gemini API key; keep it private and configure only on the backend |
| `FRONTEND_ORIGINS` | Optional additional exact origins, comma-separated |
| `MATCHING_FALLBACK_WAIT_SECONDS` | Optional; defaults to `9` before adjacent English levels can match |
| `MATCHING_REPEAT_COOLDOWN_SECONDS` | Optional; defaults to `600` seconds before recently paired users can match again if alternatives exist |

Each user may complete up to five successful partner skips in a rolling
30-minute window. The limit is enforced using existing matching queue history,
so it requires no database schema migration. A rejected or duplicate skip does
not consume a skip.

The backend always allows the exact production origins
`https://englishbuddy-for-me.vercel.app`, `https://improbuddy.in`, and
`https://www.improbuddy.in`, as well as the documented localhost development
origins. `FRONTEND_ORIGINS` adds extra exact origins, such as a custom domain or
a specific Vercel preview that needs API access. Whitespace and trailing
slashes are normalized. Do not use `*`; credentials are enabled only with the
explicit allowlist.

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

Deploy/restart the Render service after changing backend CORS configuration.
Add any additional custom domain or specific Vercel preview origin only if it
needs API access. If browser developer tools show a failed request, check both
the Render health endpoint and the `OPTIONS` preflight response for the page's
exact origin before diagnosing it as a backend outage.

## Database and secrets

- Set `DATABASE_URL`, `SECRET_KEY`, and `GEMINI_API_KEY` in the Render service
  dashboard; do not commit `.env`, database credentials, API keys, or JWT
  signing keys.
- The existing database layer expects a PostgreSQL URL compatible with
  SQLAlchemy/psycopg2. Use Render's internal database URL when the web service
  and database are in the same region.
- `SECRET_KEY` signs JWTs. Replacing it invalidates existing login tokens.
- The existing `conversation_transcripts` and `conversation_analysis` tables
  must be present in PostgreSQL. The application does not recreate or migrate
  these tables.
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
not written to files, the database, logs, or an application queue/cache. Each
successful non-empty chunk's transcript text is saved to
`conversation_transcripts` under the authenticated participant's ID. Chunk
row IDs are deterministic so a retry does not create another row. Available
chunk capture times are retained; precise word-level speech times are not
fabricated. A bounded in-memory transcript is also maintained during the call
and cleared when the conversation ends or is skipped.

After **End & Review**, the participant-authorized transcript endpoint reads
saved segments and the analysis endpoint validates Gemini's response before
saving it in `conversation_analysis`. Audio is never included in either table.
The call signaling room and reconnect grace timer are process-local, so keep
the Render service at a single Uvicorn worker unless those are moved to shared
infrastructure.

The browser's Web Speech API transcript is rendered only in that participant's
page and is not sent to the other participant. Browser vendors may use remote
speech-recognition services; this application cannot guarantee that browser
transcription is processed locally. Users who require strictly local browser
recognition should disable this feature or use a browser that provides an
on-device recognition mode.

The site does not request microphone access merely when opened. If browser
permission is already granted, it initializes the microphone when a match
starts; otherwise the user selects **Start audio with microphone** to grant
permission. Denied permissions include a prompt to update browser site settings.
All microphone tracks are stopped when the call ends. Browser speech
recognition is also opt-in: after the audio call connects, expand the transcript
panel and select **Start live transcript**
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
5. Test CORS preflight from `https://improbuddy.in` and
   `https://www.improbuddy.in` for `POST` with `Authorization,Content-Type`.
6. Allow microphone access on the first call, end it, and start another call to
   verify the saved site permission avoids an extra prompt.
7. Verify transcript rows for both authenticated speakers and the persisted
   analysis row in PostgreSQL.
8. End a call from either browser, then test a brief signaling interruption
   shorter than the reconnect grace period and a disconnect longer than it.
   Synthetic media and signaling checks do not prove microphone-based audio;
   TURN may be required.
