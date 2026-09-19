# API usage review

Review date: 2026-09-19. This is a source-level request audit, not a historical billing report or a capture of a user's vehicle responses. Apart from desktop visibility gating, the five-minute default and the two-event debug timestamps, the optimizations proposed below have **not** been implemented.

## Requests in one invocation

Counts assume valid cached authorization, no concurrent action and no API error unless stated otherwise.

| Invocation / condition | Tesla HTTP requests | Other network work |
| --- | --- | --- |
| Routine refresh with a hidden, locked, sleeping or unavailable desktop | **0**, including token renewal | **0**; saved map/readings only |
| Visible desktop, vehicle asleep/offline | **1**: `GET /api/1/vehicles` | A missing map may be retrieved for the previously saved position if explicitly enabled |
| Visible desktop, vehicle online | **2**: vehicle list, then one combined `vehicle_data` request | Address lookup or map download only when needed |
| Known Tesla rate-limit retry time still in the future | **0** | Map lookup can still run on the visible-desktop path |
| Access token due to expire | **+1** OAuth renewal, normally reused by the rest of the invocation | None |
| HTTP 401 | One forced OAuth renewal and one retry of that request | None |
| Location-inclusive live read returns HTTP 403 | **3** total: list, rejected combined read, combined read without location | No new location lookup |
| Explicit wake while offline | Initial availability read, **one wake**, status checks every five seconds for up to 90 seconds, then final availability/live reads if online | May update location/map afterwards |
| Explicit successful vehicle command while online | Preflight list + live read + capabilities, command transport, then list + live read for verification | May update location/map afterwards |

The last row is **five reads plus the command transport**. A legacy REST command adds one request, for six total before xBar's follow-up refresh. Signed commands may need session negotiation/retries inside Tesla's SDK, so one CLI execution is not necessarily one HTTP request. Climate power transitions can send two commands. Normal polling never invokes the command SDK or wake endpoint.

Sources: [`vehicle.py`](../src/tesla_bar/application/vehicle.py), [`commands.py`](../src/tesla_bar/application/commands.py), [`gateway.py`](../src/tesla_bar/infrastructure/gateway.py), [`api.py`](../src/tesla_bar/infrastructure/api.py), [`auth.py`](../src/tesla_bar/infrastructure/auth.py).

## Volume and payload

At an uninterrupted one-minute schedule with the vehicle always online, ordinary refreshes amount to roughly **1,440 live reads plus 1,440 availability reads per day**. Five minutes reduces this to **288 + 288**, an 80% reduction. If the desktop is visible for eight hours, that becomes about **96 + 96 per day**. These are scheduling estimates, not measured usage: execution time, vehicle sleep, screen pauses, errors and manual actions change the total. Reads are not all necessarily in the same billing category.

The live request explicitly selects `charge_state`, `gui_settings`, `climate_state` and `vehicle_state`; `location_data` is added only when enabled and authorized. They are sections of **one HTTP response**, not five separate requests. They support the existing battery, charging, units, climate, temperature, locks, trunks, Sentry and location features. Unrequested sections are not deliberately requested. The plugin keeps only the fields it uses, but filtering after receipt does not reduce the bytes already downloaded.

Debug info retains only the latest two request times. There is no historical request counter or raw response-size log, so exact past byte totals cannot be reconstructed from the smaller filtered cache. The JSON transport does not explicitly request gzip, and it reuses HTTPS connections only within the same invocation. A map is a separate 720 × 480 PNG, with a 3 MB acceptance cap (not its measured typical size), and is embedded locally in xBar output afterwards. Reopening the submenu does not download the image again. Address lookup uses Apple's service; map retrieval uses MapMap. Neither is a Tesla API request.

## Proposed optimizations — not applied

1. **Reuse the reading after menu actions.** Actions already fetch/verify data, then `refresh=true` makes xBar execute a normal refresh again. An online command can therefore be followed by two redundant reads. Have that specific redraw consume the just-written result, while keeping ordinary scheduled/manual refreshes fresh. Changing display mode should also need no Tesla request.
2. **Stop repeated requests after persistent access/billing failures.** Only HTTP 429 with a future retry time currently suppresses later Tesla calls. A 403/402 is attempted again on the next visible run. Add an explicit paused/error state with a controlled manual retry; do not invent a monthly quota. Retain a denied-location state until access is reauthorized instead of repeating the rejected location request each run. Also consider backoff when 429 omits `Retry-After`.
3. **Reuse maps/addresses across insignificant GPS movement.** Current cache identity uses exact coordinates. Stationary GPS jitter can trigger a new map and geocoding request every refresh. Reuse the map viewport/address within a small distance threshold and place the vehicle dot locally. This saves third-party traffic and latency, not Tesla data calls.
4. **Measure before narrowing live data further.** Optional, local, aggregate counts and response-byte totals per endpoint category would establish actual usage without tokens, VINs, coordinates or response bodies. HTTP compression may reduce bandwidth if supported, but not request-based charges. Removing sections would lose existing features; Fleet Telemetry is the larger alternative for frequent updates, but requires a reachable backend and a separate architecture decision.

Do not remove the availability check just to cut the request count: it prevents unnecessary live-data requests against a sleeping/offline vehicle. Tesla also recommends checking connectivity before requesting device data.

## Rate limit versus billing limit

Tesla documents **60 realtime-data requests per minute per device/account**, distinct from its monthly billing limit. Its billing documentation says requests returning status codes below 500 can be billable, and reaching the billing limit can suspend access. A low requests-per-minute rate therefore does not establish that usage is free. HTTP 403 by itself does not identify the exact billing/permissions cause; verify the account's Billing & Usage page. This review does not change billing settings or payment methods.

Primary references: [Tesla billing and limits](https://developer.tesla.com/docs/fleet-api/billing-and-limits), [Tesla pricing](https://developer.tesla.com/), [vehicle endpoints](https://developer.tesla.com/docs/fleet-api/endpoints/vehicle-endpoints).
