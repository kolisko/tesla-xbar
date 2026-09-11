# Set up your own Tesla connection

Every installation uses its owner's Tesla Developer application, credentials, HTTPS domain and key. The project does not provide a shared Client ID, private key or backend. Tesla approval, API access and billing requirements are controlled by Tesla.

## 1. Install locally

Install xBar, Python 3.9 or newer, Go 1.23 or newer, Git, OpenSSL and Apple's Command Line Tools. On macOS with Homebrew:

```sh
xcode-select --install
brew install python go
brew install --cask xbar
git clone https://github.com/kolisko/tesla-xbar.git
cd tesla-xbar
python3 -m scripts.install
```

The installer builds the Swift Keychain helper and a pinned version of Tesla's official command helper. For a new profile it generates an independent P-256 key in:

```text
~/Library/Application Support/Tesla xBar/command-key.pem
```

The matching public key is exported as `public-key.pem` in the same directory. The private key stays outside the checkout. Back up your private profile securely; updates preserve it and will refuse to silently generate a replacement key for an existing profile.

## 2. Host the public key

Copy **only `public-key.pem`** to this path on a public HTTPS domain you control:

```text
https://your-app.example.com/.well-known/appspecific/com.tesla.3p.public-key.pem
```

The URL must serve the PEM file directly, without authentication. A static hosting service is sufficient; the site does not forward requests to your Mac. If using a GitHub Pages user site, use the domain root and add `.nojekyll` so `.well-known` is served. Do not upload `command-key.pem`, credentials or the private profile.

See [Tesla's virtual key documentation](https://developer.tesla.com/docs/fleet-api/virtual-keys/overview).

## 3. Register your Tesla Developer application

Create your application in the [Tesla Developer portal](https://developer.tesla.com/). Use your own app name and domain. Configure:

| Setting | Value |
| --- | --- |
| Allowed origin | Your public HTTPS origin, such as `https://your-app.example.com` |
| Redirect URI | `http://localhost:8765/callback` |
| Grant types | Authorization Code and Client Credentials / Machine-to-Machine |
| Vehicle access | Vehicle Information, Vehicle Commands, Vehicle Charging Management |

The plugin requests `openid offline_access vehicle_device_data vehicle_cmds vehicle_charging_cmds`. The current version requests command scopes as well as read access because it includes wake and charging controls. Location is optional: enable **Vehicle Location** for the developer app, then choose **Location → Enable Location…** and approve that scope on Tesla’s consent page. This adds `vehicle_location`. No energy-product scopes are requested. Tesla's charging scope may cover more information than this plugin uses; inspect Tesla's consent page before granting access.

Complete any required app review and billing setup in the portal. Keep your Client Secret private. See [Tesla's authentication guide](https://developer.tesla.com/docs/fleet-api/authentication/overview) and [billing documentation](https://developer.tesla.com/docs/fleet-api/billing-and-limits).

## 4. Configure, register the region and sign in

Open **Settings…** in the xBar plugin. Enter your Client ID, Client Secret, public-key domain and region (`eu`, `na` or `cn`). The secret prompt is hidden. [`examples/config.example.json`](../examples/config.example.json) documents the non-secret fields; the installer does not copy example values over an existing profile.

Register your domain in the selected Fleet API region from Terminal:

```sh
TESLA_XBAR_ACTION="$HOME/Library/Application Support/Tesla xBar/tesla-action.sh"
"$TESLA_XBAR_ACTION" register
```

Then choose **Connect Tesla account…** in xBar, sign in on Tesla's website and grant access to your vehicle. The browser returns to a temporary localhost callback on your Mac. It closes after authorization; ongoing refresh uses the saved tokens in Keychain.

If you have multiple vehicles, choose **Select vehicle** in the menu. **Menu bar display** switches between Range and Percentage.

## 5. Enable physical commands if required by your vehicle

Reading battery data does not require adding a virtual key to the vehicle. Many vehicles require the app's key for signed charging and charge-port commands.

Camp Mode, Pet Mode, running climate and unlocked-vehicle indicators use the same
vehicle-data permission as battery readings. They need no additional consent or
virtual-key pairing. After updating, they appear when the next successful online
refresh supplies the relevant fields. The fan means `is_climate_on` is true;
an open padlock means `locked` is explicitly false. Missing or old information
does not activate an icon. Climate controls are available separately under **Clima**;
the unlock indicator does not add lock/unlock controls.

The **Clima** submenu provides normal climate, Keep Climate On, Camp Mode, Pet Mode,
temperature selection, modes off and full climate/modes off. These actions use
`vehicle_cmds`; reconnect with **Vehicle Commands** enabled if Tesla denies access.
Signed commands also require the paired app key. Normal climate and full shutdown
first exit the active keeper mode. Temperature is in °C, uses limits returned by
the vehicle, and sets both front zones in 0.5 °C steps. If limits are missing,
refresh while the vehicle is online. Setting a temperature alone does not turn
climate on. A clicked command can wake the vehicle; routine refresh cannot.

**Inside temperature** and **Outside temperature** show Tesla's measured readings,
separately from **Target temperature**. Unavailable readings are labeled as such;
saved readings from an offline/asleep vehicle or a failed refresh use **Last known**.

When upgrading from a version without Clima controls, use the full installer
(`python3 -m scripts.install`) to rebuild the command helper with its mode adapter.

Choose **Charging and port → Add key to vehicle…**, open the link on a phone with the Tesla app and approve the key for the correct vehicle. The link uses your configured domain. Then choose **Check command setup**.

Test physical commands yourself when appropriate. **Start charging**, **Stop charging** and port actions can wake the vehicle. Ordinary **Refresh now** does not send wake commands. Opening a port is not a physical cable-removal mechanism.

## Updating

```sh
git pull --ff-only
python3 -m scripts.install
```

For an update that only changes Python code or the wrapper, you can reuse installed helpers:

```sh
python3 -m scripts.install --runtime-only
```

Both paths preserve configuration, keys, tokens, saved readings and the active wrapper's interval. The runtime-only path must not be used when an update requires new helper binaries. Never copy another person's profile or signing key.

## Troubleshooting

- **Offline / asleep:** the last known reading remains visible. A last known connected cable keeps the text green; otherwise it is gray. The original timestamp and **Last known cable state** remain in the menu. Use the explicit wake action only when you want to wake the car.
- **No data yet:** confirm registration, region, consent and the vehicle's connectivity.
- **Missing key:** pair your own app key in the Tesla mobile app. Do not create a new key to fix an existing profile unless you also update the hosted public key and vehicle pairing.
- **Expired login:** reconnect the account. Tokens normally refresh automatically.
- **Busy notice:** another operation is running; the rejected action is not queued. Try again after it finishes.
- **Billing / rate-limit error:** follow Tesla's portal instructions. The plugin honors the server's retry delay.
- **Port 8765 unavailable:** close an earlier sign-in attempt or free the local port before reconnecting.

Do not paste tokens, callback URLs, VINs or private profile files into GitHub issues. Use fictional examples and redact screenshots.

## Sentry and Location

**Sentry** uses `vehicle_cmds` and the existing paired virtual key. Clicking on/off may wake an unavailable vehicle. A normal refresh only reads Sentry state.

**Location** is disabled by default. To enable it:

1. In the Tesla Developer portal, open your app’s scope management and enable **Vehicle Location**.
2. In xBar, choose **Location → Enable Location…**.
3. On Tesla’s consent page, allow **Vehicle Location**. Existing battery and command permissions remain requested.
4. Refresh the plugin while the vehicle is online. The Location submenu shows the address and **Open in Apple Maps**. It does not automatically wake the car.

Enabling Location shares the vehicle’s latitude/longitude with Apple’s geocoding service to obtain an address. It does not read your Mac’s location or send Apple your Tesla credentials or VIN. Address lookup runs only when needed and is bounded to eight seconds; no daemon is installed. Existing coordinates reuse their matching address. Changed coordinates never inherit the old address.

Offline/asleep vehicles retain the last known position and its original time. If Apple has no address or lookup fails, the map still opens the coordinate. An address may lack a house number or describe the nearest street; it cannot identify an exact parking space. Tesla may show its location-sharing indicator in the vehicle.

**Disable Location** clears the saved location/address and rendered map link and stops requesting GPS data. It does not revoke Tesla’s server-side permission; use Tesla account permissions to revoke that separately.
