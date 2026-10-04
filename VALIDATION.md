# Validation — 24 September 2026

## Executed successfully for this package

- **31 Python tests**: account/vehicle isolation, CSRF, admin-only deletion, suspended/deleted users, token checks and rotation, upload disable/restore, password changes, cleanup grace/resume, geofence ownership/locking, radius/polygon/hole calculations, warning clocks, stale GPS, ETag conflict retries, history acknowledgement failure/retry, pagination, login throttling and per-vehicle transaction scope.
- **13 Firebase Realtime Database rules-emulator tests**: owner/admin reads, cross-customer denial, anonymous denial, suspended accounts, deleted owners/vehicles, stale session claims, private token-hash denial, parent/history read denial and browser write denial.
- **Actual RTDB emulator integration using HTTP REST**: Flask login, customer registration, vehicle registration, authenticated GPS POST, history write, live projection, geofence warning and customer deletion. This exercises the real ETag/REST server rather than only an in-memory replacement.
- **Frontend smoke checks for customer and admin modes**: local Fit action makes no API call; selection, history pagination response handling, route-gap rendering and clearing work. JavaScript syntax checked.
- **ESP8266 tracker compiled** for NodeMCU ESP-12E with ESP8266 core 3.1.2, TinyGPSPlus 1.0.3, ArduinoJson 7.4.3, DFRobotDFPlayerMini 1.0.6, 4MB flash / 1MB filesystem. Static RAM 32,756 / 80,192 bytes; instruction RAM 62,607 / 65,536 bytes; flash code 439,112 / 1,048,576 bytes. Audio disabled in the supplied configuration.
- **Separate filesystem formatter compiled** for the same board/layout.

Backend tests used Python 3.12. The syntax and pinned dependencies support Python 3.10+, but this environment did not separately execute Python 3.10. ESP32 conditional code is retained for adaptation; only the requested ESP8266 build was compiled here.

## Not claimed

No physical GPS, ESP8266, DFPlayer, car interlock, real hotspot, your PythonAnywhere worker, your Firebase project or your Mapbox account was available for a live end-to-end test. Firebase Authentication custom-token exchange must be verified with your configuration using `check-live`. Browser smoke tests use a map stub; they do not validate your Mapbox token or a rendered map on your device.

A compiled sketch and passing tests do not establish a maximum one-second delivery time, automotive certification or production uptime. Verify your actual network, TLS chain, supply voltage, GPS reception, Firebase usage and host capacity before operational use. ESP8266 instruction RAM is close to its limit; adding more embedded libraries can exceed it.

Default history buckets are five seconds. The tracker captures its persistent offline queue every five seconds but may miss uncaptured fixes while synchronous HTTPS blocks GPS parsing. Flash storage is bounded and has finite write endurance. This is not a lossless black-box recorder. The queue keeps old data and drops new samples when full; corrupt/expired ESP8266 queue entries are reported and discarded.

No private account keys, service-account JSON, real Wi-Fi passwords or device tokens are included. The bundled CA certificates are public trust anchors. No running-engine cutoff is implemented.
