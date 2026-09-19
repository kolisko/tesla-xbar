# API usage review

Review date: 2026-09-19. This is a source-level request audit, not a historical billing report or a capture of a user's vehicle responses. Implemented savings include desktop visibility gating, the five-minute default, progressive error backoff and reuse of the plugin's explicit Refresh now result during the immediate menu redraw. The remaining proposals below are **not** implemented.

## Requests in one invocation

Counts assume valid cached authorization, no concurrent action and no API error unless stated otherwise.

| Invocation / condition | Tesla HTTP requests | Other network work |
| --- | --- | --- |
| Routine refresh with a hidden, locked, sleeping or unavailable desktop | **0**, including token renewal | **0**; saved map/readings only |
| Visible desktop, vehicle asleep/offline | **1**: `GET /api/1/vehicles` | A missing map may be retrieved for the previously saved position if explicitly enabled |
| Visible desktop, vehicle online | **2**: vehicle list, then one combined `vehicle_data` request | Address lookup or map download only when needed |
| Local error backoff or Tesla rate-limit retry time still in the future | **0** | **0**; saved map/readings only |
| Plugin's explicit Refresh now | Normal availability/live requests, bypassing local error backoff; Tesla's rate-limit deadline is still honored | Normal location/map work if needed |
| Immediate xBar redraw after the plugin's Refresh now | **0** for five seconds after the action completes | **0**; reuse the manual result |
| Access token due to expire | **+1** OAuth renewal, normally reused by the rest of the invocation | None |
| HTTP 401 without an active Retry-After | One forced OAuth renewal and one retry of that request | None |
| Location-inclusive live read returns HTTP 403 without an active Retry-After | **3** total: list, rejected combined read, combined read without location | No new location lookup |
| Explicit wake while offline | Initial availability read, **one wake**, status checks every five seconds for up to 90 seconds, then final availability/live reads if online | May update location/map afterwards |
| Explicit successful vehicle command while online | Preflight list + live read + capabilities, command transport, then list + live read for verification | May update location/map afterwards |

The last row is **five reads plus the command transport**. A legacy REST command adds one request, for six total before xBar's follow-up refresh. Signed commands may need session negotiation/retries inside Tesla's SDK, so one CLI execution is not necessarily one HTTP request. Climate power transitions can send two commands. Normal polling never invokes the command SDK or wake endpoint.

After three failed refresh attempts, the next automatic attempt waits 15 minutes, then 30 minutes after the next failure, then one hour after each further failure. Waiting invocations do not advance the failure count or deadline. This applies to access/billing failures, network errors, invalid readings and rate limits (including those without `Retry-After`); a longer server deadline wins. Normal offline/asleep/unavailable-vehicle responses reset the error state. The plugin's own **Refresh now** is a separate explicit action; built-in xBar refreshes cannot bypass the local wait. Debug info shows the earliest retry time, subject to the next visible xBar run.

For surfaced Python Fleet API/OAuth read or wake errors, the latest actual `Retry-After` header is retained with its receipt time and parsed delay. Both seconds and HTTP dates are supported, including on non-429 errors such as 503 or 403. Debug info shows the original value, server deadline, waiting/elapsed state and which policy controls the next automatic attempt. This is one saved advice record, not a response log; expired advice remains visible with its original timestamp. An absent header is not invented, and unparseable advice is displayed without creating a server deadline. Historical responses from before this feature cannot be reconstructed. Signed-command SDK response headers are not exposed by the CLI and are not included.

Sources: [`vehicle.py`](../src/tesla_bar/application/vehicle.py), [`commands.py`](../src/tesla_bar/application/commands.py), [`gateway.py`](../src/tesla_bar/infrastructure/gateway.py), [`api.py`](../src/tesla_bar/infrastructure/api.py), [`auth.py`](../src/tesla_bar/infrastructure/auth.py).

## Volume and payload

At an uninterrupted one-minute schedule with the vehicle always online, ordinary refreshes amount to roughly **1,440 live reads plus 1,440 availability reads per day**. Five minutes reduces this to **288 + 288**, an 80% reduction. If the desktop is visible for eight hours, that becomes about **96 + 96 per day**. These are scheduling estimates, not measured usage: execution time, vehicle sleep, screen pauses, errors and manual actions change the total. Reads are not all necessarily in the same billing category.

The live request explicitly selects `charge_state`, `gui_settings`, `climate_state` and `vehicle_state`; `location_data` is added only when enabled and authorized. They are sections of **one HTTP response**, not five separate requests. They support the existing battery, charging, units, climate, temperature, locks, trunks, Sentry and location features. Unrequested sections are not deliberately requested. The plugin keeps only the fields it uses, but filtering after receipt does not reduce the bytes already downloaded.

Debug info retains only the latest two request times. There is no historical request counter or raw response-size log, so exact past byte totals cannot be reconstructed from the smaller filtered cache. The JSON transport does not explicitly request gzip, and it reuses HTTPS connections only within the same invocation. A map is a separate 720 × 480 PNG, with a 3 MB acceptance cap (not its measured typical size), and is embedded locally in xBar output afterwards. Reopening the submenu does not download the image again. Address lookup uses Apple's service; map retrieval uses MapMap. Neither is a Tesla API request.

## Proposed optimizations — not applied

1. **Reuse the reading after menu actions.** Actions already fetch/verify data, then `refresh=true` makes xBar execute a normal refresh again. An online command can therefore be followed by two redundant reads. Have that specific redraw consume the just-written result, while keeping ordinary scheduled/manual refreshes fresh. Changing display mode should also need no Tesla request.
2. **Consider a full pause after confirmed billing/access denial.** Progressive 15/30/60-minute retry backoff is implemented, but still attempts hourly during a persistent failure. A future opt-in policy could stop automatic attempts completely until a manual retry. Retain a denied-location state until access is reauthorized instead of repeating a rejected location request followed by a successful fallback each run. Do not invent a monthly quota.
3. **Reuse maps/addresses across insignificant GPS movement.** Current cache identity uses exact coordinates. Stationary GPS jitter can trigger a new map and geocoding request every refresh. Reuse the map viewport/address within a small distance threshold and place the vehicle dot locally. This saves third-party traffic and latency, not Tesla data calls.
4. **Measure before narrowing live data further.** Optional, local, aggregate counts and response-byte totals per endpoint category would establish actual usage without tokens, VINs, coordinates or response bodies. HTTP compression may reduce bandwidth if supported, but not request-based charges. Removing sections would lose existing features; Fleet Telemetry is the larger alternative for frequent updates, but requires a reachable backend and a separate architecture decision.

Do not remove the availability check just to cut the request count: it prevents unnecessary live-data requests against a sleeping/offline vehicle. Tesla also recommends checking connectivity before requesting device data.

## Rate limit versus billing limit

Tesla documents **60 realtime-data requests per minute per device/account**, distinct from its monthly billing limit. Its billing documentation says requests returning status codes below 500 can be billable, and reaching the billing limit can suspend access. A low requests-per-minute rate therefore does not establish that usage is free. HTTP 403 by itself does not identify the exact billing/permissions cause; verify the account's Billing & Usage page. This review does not change billing settings or payment methods.

Primary references: [Tesla billing and limits](https://developer.tesla.com/docs/fleet-api/billing-and-limits), [Tesla pricing](https://developer.tesla.com/), [vehicle endpoints](https://developer.tesla.com/docs/fleet-api/endpoints/vehicle-endpoints).
