# FleetRTDB

Flask on PythonAnywhere + Firebase Realtime Database + ESP8266 D5 GPS firmware.

**Start with `DEPLOYMENT.md` or open `START_HERE.html`.** Configure your accounts and keys; no private credentials are bundled. No Firebase Cloud Functions or Blaze deployment is required.

Included:
- Administrator/customer logins, account suspension, password management.
- Vehicle registration, hashed device tokens, station MAC check, token rotation, upload enable/disable.
- Admin-only customer/vehicle deletion with immediate access revocation and resumable cleanup.
- Customer-scoped realtime Firebase listeners, customer/vehicle filters, fit/follow controls.
- History with pagination, observed route lines, gaps and estimated stops.
- Radius boundaries with explicit centre, imported city boundaries, Polygon/MultiPolygon support and admin boundary lock.
- Two-stage geofence warnings and manual 10-minute warnings; safe 0/1 **restart request**, no engine-cutoff implementation.
- ESP8266 GPS TX→D5, optional DFPlayer, bounded offline LittleFS queue, verified TLS, Wi-Fi/HTTP diagnostics.
- Deployment checks, tests, security rules and maintenance commands.

Live upload interval targets one second; actual delivery depends on GPS, hotspot, TLS and server load. History uses five-second time buckets by default. Firebase limits and host capacity still apply. This is source code to deploy and validate with your hardware, not a claim of automotive certification or an already-hosted service.

## Layout

`app.py`: Flask routes and CLI; `rtdb_store.py`: proxy-compatible Firebase REST/ETag transport; `domain.py`: geometry and warning state machine; `static/` and `templates/`: dashboard; `database.rules.json`: browser read permissions and indexes; `firmware/`: tracker and optional formatter; `tools/`: TLS and simulated upload diagnostics; `tests/`: backend, transport, UI, emulator security/integration tests.

All fleet persistence uses RTDB. Firebase Authentication is only the browser live-listener bridge; Flask owns customer login/password verification. The service account signs short-lived custom tokens. Password and token hashes are never in the readable live projection.

Uploads use a per-vehicle ETag transaction for metadata/live state. Administrative operations use a metadata transaction; history is stored separately, outside those snapshots. History writes are idempotent and must succeed before upload acknowledgement. There can be a temporary live/history difference during a history-write failure; the tracker retains its queued batch and retries. Deletion cleanup has a grace interval for in-flight writes.

History is one representative observation per time bucket, not reconstructed road geometry. Stop estimates require speed <=2km/h, positions within 40m and at least three minutes of observations; gaps over 30s break a route. Payment due dates are records only; suspension is an explicit admin action. A restriction cannot be freshly delivered while the tracker is offline.

## Developer checks

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
node tests/ui_smoke.cjs
```

Optional Firebase rules emulator tests need Node 20+ and Java (tested with Java17; use Java21 for newer tooling):

```bash
npm install
npm run test:rules
npx firebase emulators:exec --only database --project demo-fleetrtdb "python tests/emulator_integration.py"
```

These use a demo project only. Firebase CLI is not required to deploy the Flask app or publish rules through the Firebase Console.

## Official references

- https://firebase.google.com/docs/database/rest/auth
- https://firebase.google.com/docs/database/rest/save-data
- https://firebase.google.com/docs/auth/admin/create-custom-tokens
- https://firebase.google.com/docs/database/usage/billing
- https://firebase.google.com/docs/database/usage/limits
- https://help.pythonanywhere.com/pages/Flask/
- https://help.pythonanywhere.com/pages/403ForbiddenError/
- https://arduino-esp8266.readthedocs.io/en/3.1.2/esp8266wifi/bearssl-client-secure-class.html

See `VALIDATION.md` for checks actually performed and limits of testing.
