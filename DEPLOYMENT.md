# FleetRTDB — step-by-step deployment

Use this guide in order. It installs a new project alongside your old working tracker; do not overwrite the old directory or reuse its database root. You need your Firebase account, PythonAnywhere account, and Mapbox public token. No Cloud Functions deployment or Blaze upgrade is used.

## 1. Prepare Firebase

1. Open https://console.firebase.google.com/ and select your intended project. A separate project/database for this installation avoids mixing old schemas.
2. Copy the **Project ID** from Project settings → General. Use the SAME project in every following step.
3. Open **Build → Authentication → Get started**. This initializes Firebase Authentication. The app uses custom-token sign-in; customers are created in FleetRTDB, not manually in the Firebase Authentication console. You do not need anonymous authentication.
4. In Authentication → Settings → Authorized domains, add your exact PythonAnywhere hostname, such as `yourusername.pythonanywhere.com` (no `https://` or path).
5. Open **Build → Realtime Database → Create database**. Choose a suitable region and start in locked mode. This is **Realtime Database**, not Cloud Firestore.
6. Copy the database URL shown above the data tree. Examples are `https://PROJECT-default-rtdb.firebaseio.com` or `https://PROJECT-default-rtdb.asia-southeast1.firebasedatabase.app`. Copy YOUR exact URL; do not construct it from these examples.
7. Open its **Rules** tab, replace the contents with `database.rules.json` from this package, and click **Publish**. Do not set public read/write to true.
8. Project settings → General → Your apps → add a **Web app** if none exists. Copy its `apiKey`; this is `FIREBASE_WEB_API_KEY` below. Firebase Hosting is not required.
9. Project settings → Service accounts → Generate new private key. Save the original JSON file unchanged. It belongs on the server only, outside the public/static folder.

Your browser may show public Firebase configuration, but private service-account credentials and vehicle tokens must never be included in frontend JavaScript. The supplied rules allow a signed-in customer to read only their own sanitized live vehicle data. All browser database writes are denied; changes go through the authenticated Flask backend.

## 2. Upload to PythonAnywhere

Upload `FleetRTDB.zip` to your PythonAnywhere home directory. Open a **Bash console**, then paste these commands with their line breaks:

```bash
cd ~
unzip FleetRTDB.zip
cd ~/FleetRTDB
python3 --version
python3 -m venv ~/.virtualenvs/fleetrtdb
source ~/.virtualenvs/fleetrtdb/bin/activate
python -m pip install -r requirements.txt
mkdir -p ~/private
chmod 700 ~/private
cp .env.example .env
python -c "import secrets; print(secrets.token_hex(32))"
```

Python 3.10 or newer works. Your earlier console reported Python 3.10.5; there is no need for a `python3.11` command. Keep the generated random value for `SECRET_KEY`.

Using PythonAnywhere's **Files** page, upload the downloaded JSON to:

```text
/home/YOUR_USERNAME/private/firebase-service-account.json
```

Replace `YOUR_USERNAME` with the actual case-sensitive home-directory name shown in your console. For your earlier account this was `ThinkBitLabs`; use the account that will host this deployment.

Then run:

```bash
chmod 600 ~/private/firebase-service-account.json
chmod 600 ~/FleetRTDB/.env
```

## 3. Configure the server

Open `~/FleetRTDB/.env` in the Files editor. Replace every placeholder:

```dotenv
SECRET_KEY=PASTE_THE_NEW_RANDOM_HEX_VALUE
FIREBASE_PROJECT_ID=YOUR_PROJECT_ID
FIREBASE_DATABASE_URL=https://YOUR_EXACT_DATABASE_URL
FIREBASE_SERVICE_ACCOUNT=/home/YOUR_USERNAME/private/firebase-service-account.json
FIREBASE_WEB_API_KEY=YOUR_WEB_APP_API_KEY
MAPBOX_TOKEN=YOUR_MAPBOX_PUBLIC_PK_TOKEN
HISTORY_INTERVAL_SECONDS=5
```

- `MAPBOX_TOKEN` starts with `pk.`. Use your own working Mapbox token, not a Google Maps API key. If its URL restrictions are enabled, allow your PythonAnywhere domain. Mapbox has its own usage limits.
- Live tracker uploads target **one second**. `HISTORY_INTERVAL_SECONDS=5` groups stored history into five-second time buckets; the last accepted observation in a bucket is retained. Set `1` for one-second history with higher storage use.
- Old Firestore documents are not automatically migrated. This is a fresh RTDB installation.

Run:

```bash
cd ~/FleetRTDB
source ~/.virtualenvs/fleetrtdb/bin/activate
python -m flask --app app check-firebase
python -m flask --app app create-admin
python -m flask --app app check-live
```

`create-admin` asks for login ID, display name and a password of at least 12 characters. Password entry is hidden; type it and press Enter.

Expected checks:

```text
Realtime Database read/write/delete succeeded.
Administrator created in Realtime Database.
Firebase custom-token sign-in succeeded. Browser live authentication is configured.
```

**Do not skip these checks.** If `CONFIGURATION_NOT_FOUND` appears, return to Firebase **Authentication → Get started**, and verify the web API key, service-account project and Project ID all belong to the same project. Valid service-account JSON alone does not initialize Authentication.

PythonAnywhere free accounts restrict outbound requests. These checks must reach your exact RTDB host, `oauth2.googleapis.com`, and `identitytoolkit.googleapis.com`. This transport uses HTTPS REST through `requests`, which honors PythonAnywhere's proxy. If access is denied by the host's allowlist, ask PythonAnywhere to allow that exact Firebase hostname. Do not weaken Firebase rules or disable TLS to work around a proxy restriction.

## 4. Configure PythonAnywhere Web

In **Web → Add a new web app**, select your domain, **Manual configuration**, and the same Python version used for the virtual environment (for your earlier setup: **Python 3.10**).

Set these fields, replacing `YOUR_USERNAME`:

| Field | Value |
|---|---|
| Source code | `/home/YOUR_USERNAME/FleetRTDB` |
| Working directory | `/home/YOUR_USERNAME/FleetRTDB` |
| Virtualenv | `/home/YOUR_USERNAME/.virtualenvs/fleetrtdb` |
| Static URL | `/static/` |
| Static directory | `/home/YOUR_USERNAME/FleetRTDB/static/` |

Click the **WSGI configuration file** link and replace its contents with:

```python
import sys

project = '/home/YOUR_USERNAME/FleetRTDB'
if project not in sys.path:
    sys.path.insert(0, project)

from app import create_app
application = create_app()
```

Save and click the green **Reload** button on the Web page. Turn on **Force HTTPS** if available. Open:

```text
https://YOUR_USERNAME.pythonanywhere.com/login
```

Sign in with the administrator created above. The connection label should say live Firebase updates are connected after successful sign-in. Opening `/api/gps` directly in a browser is not a GPS upload; the device sends an authenticated POST.

Do not run `flask run` or keep a Bash console running for hosting. PythonAnywhere runs the WSGI app. Reload the Web app after changing `.env`, Python files, or installed packages; hard-refresh the browser after frontend changes.

## 5. Register the customer and vehicle

1. In Administration, create a customer login/password.
2. Register a vehicle with name, registration, customer, a unique Device ID such as `ESP8266_GPS1`, and the ESP8266's **station MAC**.
3. Copy the device token shown once. Save it privately. The database stores a hash; the hash will not work in firmware.
4. Use a different Device ID and generated token for each tracker.

You can initially flash the firmware to read its station MAC in Serial Monitor, then finish registration and flash the generated token. Wrong or missing tokens are rejected; there is no unauthenticated legacy upload mode.

## 6. Install Arduino support and wire the GPS

In Arduino IDE:

1. Preferences → Additional Boards Manager URLs: add `https://arduino.esp8266.com/stable/package_esp8266com_index.json`.
2. Boards Manager → install **esp8266 by ESP8266 Community**, version **3.1.2**.
3. Select **NodeMCU 1.0 (ESP-12E Module)** and your COM port.
4. Select **4MB flash with 1MB filesystem** (menu wording may be `4MB (FS:1MB OTA:~1019KB)`). Keep this filesystem layout for later uploads.
5. Library Manager: install **TinyGPSPlus 1.0.3**, **ArduinoJson 7.4.3**, and **DFRobotDFPlayerMini 1.0.6**. Install the audio library even if audio is disabled.

Connections:

| GPS connection | ESP8266 connection |
|---|---|
| GPS TX | **D5 / GPIO14** |
| GPS GND | GND |
| GPS RX | Leave disconnected |
| GPS VCC | Supply required by your particular GPS breakout board |

ESP8266 GPIO uses **3.3V logic**. Do not apply a 5V serial output to D5. Power requirements depend on the GPS breakout, not just the NEO chip name. Use a stable regulated supply; a vehicle battery must not connect directly to the development board.

Open `firmware/FleetTracker/FleetTracker.ino`. In the adjacent `config.h`, edit:

```cpp
#define WIFI_SSID "YOUR_2.4_GHZ_HOTSPOT"
#define WIFI_PASSWORD "YOUR_PASSWORD"
#define SERVER_URL "https://YOUR_USERNAME.pythonanywhere.com/api/gps"
#define DEVICE_ID "ESP8266_GPS1"
#define DEVICE_TOKEN "THE_ORIGINAL_GENERATED_TOKEN"
```

Keep `GPS_RX_PIN 14`. Keep `AUDIO_ENABLED false` until audio hardware is installed. Copy an SSID exactly, including spaces. The hotspot must offer 2.4GHz and must travel with the vehicle.

The supplied `ROOT_CA` includes ISRG Root X1 and X2 for supported Let's Encrypt certificate chains. Keep TLS verification enabled. If your actual hostname uses a different chain, inspect the certificate hierarchy and install its authentic root CA. Root certificates and server chains can change; the firmware prints UTC, DNS, TLS and memory diagnostics to help identify the issue.

Compile and upload. Open Serial Monitor at **115200 baud**.

If it says `LittleFS mount failed` on a new board:

1. Upload `firmware/format_flash/format_flash.ino` with the same board and flash layout.
2. At 115200 baud, type `FORMAT` and send with New Line. This erases queued history; do it only when intended.
3. Upload `FleetTracker.ino` again.

Expected progression:

```text
WiFi connecting...
WiFi CONNECTED. IP: ...
Station MAC: ...
Device ID: ESP8266_GPS1
GPS=fresh ...
HTTP=200 ...
restart_inhibit_requested=0 engine_cutoff=0 phase=normal ...
```

Place the GPS antenna outdoors with a clear sky view. Valid coordinates in Serial Monitor confirm GPS reception; only `HTTP=200` with the accepted JSON response confirms server upload. Queued records are removed only after that acknowledgement.

## 7. Verify end-to-end operation

1. Leave the dashboard open. Move the tracker outdoors: the marker should update without pressing any button.
2. Press **Fit vehicles**, then load history. Tracking listeners continue independently. Fit is a local map action and sends no server request.
3. Sign in as a customer in a private browser window. Confirm that only that customer's vehicles appear.
4. Select a vehicle → Allowed area → Radius. Enter a centre latitude/longitude or click the map, enter kilometres, and save.
5. For a city, the admin first imports a verified Polygon/MultiPolygon GeoJSON. The owner then selects that city. A typed city name is not treated as a boundary.
6. Test warnings with a stationary tracker and a temporary test boundary. Returning inside clears the geofence warning; a separate manual block stays active until cancelled.
7. Suspend the test customer's login. Their session/live access is revoked, while the administrator can still track the vehicle.
8. Test deletion on a disposable account/vehicle. Only the administrator sees deletion controls; the backend independently enforces the role. Confirm the exact login/device ID when prompted.
9. In Journey and stops, choose a Pakistan-time date and load the route. Use **Load more points** until the full day has loaded. Long observation gaps are not joined by an invented route.

Optional isolation test: from a PC run `python tools/device_check.py` (install `requests` first). It asks for your device token without displaying it and sends an explicitly simulated position only after you type `SEND`. Use a test vehicle. A successful simulated upload plus a failing board upload isolates firmware/network/TLS from the web backend.

## 8. Audio and the 0/1 response

Optional DFPlayer: GPIO4 / **D2** through a roughly 1k series resistor to DFPlayer RX, common ground, correctly rated power, speaker connected per the module datasheet. GPS continues on D5. Set `AUDIO_ENABLED true` after installation.

Record the Urdu/English scripts in `VOICE_SCRIPTS.md` as MP3 files named `/mp3/0001.mp3` through `/mp3/0004.mp3` on the DFPlayer microSD. Audio recordings are not included. The firmware transmits play commands; it does not confirm audible playback.

| Condition | Voice | Server command |
|---|---|---|
| Normal / within boundary | None | `stop_request: 0` |
| Outside boundary, first 60s of fresh observations | 0001 | `0` |
| Still outside, next 60s | 0002 | `0` |
| Still outside after 120s | 0004 | `1` |
| Admin block first received, first 600s | 0003 | `0` |
| Admin block after 600s | 0004 | `1` |

**`1` requests restart inhibition through a separate professionally engineered interlock. This package does not stop a running engine, drive an engine relay, or claim that GPS speed proves the engine is off.** `engine_cutoff` is always `0`. Commands expire on the tracker after 15 seconds without a valid response; connection loss is reported. Boundary timers reset after stale GPS or a prolonged contact gap. Manual block timing starts at the first accepted upload after the request. Warnings and updated restrictions require working connectivity.

## 9. Maintenance and free-tier capacity

Run this daily, using PythonAnywhere Tasks if your account offers a scheduled task, or run it manually:

```bash
/home/YOUR_USERNAME/.virtualenvs/fleetrtdb/bin/python -m flask --app /home/YOUR_USERNAME/FleetRTDB/app.py purge-deleted
/home/YOUR_USERNAME/.virtualenvs/fleetrtdb/bin/python -m flask --app /home/YOUR_USERNAME/FleetRTDB/app.py prune-history --days 7
```

Deletion revokes access immediately. Physical history cleanup waits at least **20 minutes** for in-flight requests to finish, then the cleanup command removes records. Run it again if it reports waiting. The cleanup is resumable after failure. Username/device-ID reservations and minimal deletion audit metadata remain; register a new Device ID for a new ownership period.

`prune-history --days 7` permanently removes points/events older than seven days. Export a private Firebase backup before pruning if you need longer records. Without running this command, history continues growing. There is no promise of unlimited free historical storage.

Firebase Spark currently has 1GB RTDB storage, 10GB/month download allowance, and 100 simultaneous connections. Server reads, live viewers, reconnects and loading history all use bandwidth. RTDB avoids Firestore's per-document write quota, but it is not unlimited. Start with one test vehicle, inspect Firebase Usage after a representative day, and adjust retention/history/live intervals to fit your account. Each browser uses a connection for its listeners. The admin metadata operations read fleet metadata; this edition is intended for a small fleet, not thousands of vehicles.

Free PythonAnywhere capacity, expiry/renewal requirements and outbound access also apply. A Spark project plus free PythonAnywhere is possible within their limits; continuous high-frequency operation of an arbitrary fleet is not guaranteed to remain free. No Blaze-only deployment command is required.

## 10. Troubleshooting

| Symptom | Check |
|---|---|
| `auth/configuration-not-found` | Initialize Authentication, use a web API key from the SAME project, run `check-live` |
| `permission_denied` in live listener | Publish supplied RTDB rules, confirm session version/account status; sign out/in after account changes |
| Service-account JSON error | Upload original downloaded JSON, not pasted HTML or an empty file |
| Firebase 403 / proxy block | Exact database hostname, service-account IAM access, PythonAnywhere outbound allowlist |
| Map unavailable | Own valid Mapbox `pk.` token, URL restrictions, usage limits, browser network requests |
| HTTP `-1` | Failure before a usable HTTP response: inspect DNS, UTC, BearSSL error, TCP443 and heap logs |
| `Chain could not be linked to a trust anchor` | Correct hostname and current certificate root chain; keep certificate verification enabled |
| HTTP 401 | Original generated token; never its database hash; token may have been rotated |
| HTTP 403 | Device ID, station MAC, upload-enabled status, deleted customer/vehicle |
| HTTP 400 | Valid UTC fix time, coordinates, queue records no older than 30 days |
| HTTP 404 / HTML response | Exact `/api/gps` URL and correct WSGI app |
| GPS no fix | GPS TX→D5, common ground, supported power, clear sky; no-fix data is not a position |
| Queue growing | Upload throughput is below sample creation; diagnose first, reduce frequency if necessary |
| Web app import error | Web Python version matches virtualenv, correct WSGI path and installed requirements |
| Live updates slower than 1s | Inspect `elapsed_ms` and `server_ms`; internet/TLS/backend scheduling are part of latency |

The API client reports failures and keeps unsent observations rather than pretending they arrived. The bounded offline queue holds up to 1,000 captured samples, normally five seconds apart; it drops new samples when full. Synchronous ESP8266 HTTPS can delay GPS parsing, so it cannot guarantee every fix during slow requests. Confirm performance with your actual board, hotspot and hosted account before relying on it operationally.

Sources checked: Firebase RTDB REST authentication and ETag transactions, Firebase custom authentication, PythonAnywhere Flask deployment, Firebase RTDB billing. See README for links.
