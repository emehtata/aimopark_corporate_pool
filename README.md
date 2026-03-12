# Aimo Park Corporate Pool — Home Assistant Integration

A custom component that exposes the number of **free parking spaces** in your employer's [Aimo Park](https://www.aimopark.io/) corporate pooling group as a Home Assistant sensor.

## Features

- **`sensor.aimo_park_free_spaces`** — real-time free space count for your corporate pool
- **Time-windowed polling** — polls more aggressively during the busy morning rush and backs off outside working hours, minimising unnecessary API calls
- **Offline caching** — serves a randomised-TTL cache when outside active polling windows so HA never hits the API needlessly
- **Refresh token rotation** — automatically stores a new refresh token when the server issues one, so authentication stays valid long-term
- **Force-refresh service** — `aimo_park.force_refresh` skips the cache on demand (useful in automations)
- **Configurable windows & TTLs** — all timing thresholds are adjustable after setup via **Settings → Integrations → Aimo Park → Configure**

## Requirements

- Home Assistant with custom components support (e.g. installed via HACS or manually)
- An Aimo Park account with access to a corporate pooling group
- The account's **refresh token** and the pool's **pooling group ID** (see below)

## Installation

1. Copy the `aimo_park/` folder into your `config/custom_components/` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and search for **Aimo Park Corporate Pool**.

## Configuration

During setup you will be prompted for three values:

| Field | Description |
|---|---|
| **Refresh token** | Long-lived credential from the Aimo web app (see below) |
| **Pool ID** | `poolingGroupUid` of your employer's pool (see below) |
| **Country code** | Two-letter country code, e.g. `FI` (default) |

The refresh token is validated against the Aimo authentication server before the entry is created — if the token is invalid or the server is unreachable you will see an error in the setup form.

## How to get the refresh token

1. Open [https://aimoapp.aimopark.io/](https://aimoapp.aimopark.io/) in your browser and log in with your Aimo account.
2. Open the browser **Developer Tools** (press `F12` or `Ctrl+Shift+I`).
3. Navigate to the **Application** tab (Chrome/Edge) or **Storage** tab (Firefox).
4. Expand **Local Storage** and select the `https://aimoapp.aimopark.io` entry.
5. Find the key whose value contains `"credentialType": "RefreshToken"`.
6. Copy the value of the **`secret`** property — this is your refresh token.

> **Security note:** treat the refresh token like a password. It grants access to your Aimo account. Do not share it or commit it to version control.

## How to get the Pool ID

1. While logged in to [https://aimoapp.aimopark.io/](https://aimoapp.aimopark.io/), navigate to your **pooling permission** (the corporate pool page).
2. Open **Developer Tools → Network** tab and filter by `graphql`.
3. Look for a request named `GetPoolingGroupCapacity`.
4. Open the request's **Payload** (or **Request Body**) and find the `variables` object:
   ```json
   {
     "operationName": "GetPoolingGroupCapacity",
     "variables": { "poolingGroupId": "copy-this-value" },
     ...
   }
   ```
5. Copy the value of `poolingGroupId` — this is your Pool ID.

## Polling windows (Helsinki timezone, weekdays only)

| Window | Default time range | Behaviour |
|---|---|---|
| **Busy (fast)** | 07:45 – 09:15 | Fetches on every coordinator wake-up (every 60 s) |
| **Normal** | 09:15 – 13:00 | Serves cache up to the normal cache TTL (default 300 s) |
| **Outside hours** | all other times & weekends | Serves cache up to a randomised TTL (default 600 – 1200 s) |

All window boundaries and TTLs can be changed after setup via **Settings → Integrations → Aimo Park → Configure**.

## Force-refresh service

Call `aimo_park.force_refresh` to bypass the cache immediately:

```yaml
service: aimo_park.force_refresh
# Optional: target a specific entry when multiple pools are configured
data:
  entry_id: "<config_entry_id>"
```

## Sensor attributes

| Attribute | Description |
|---|---|
| `state` | Number of free spaces (integer) |
| `pool_id` | The configured pooling group ID |

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Setup fails with *"Could not authenticate"* | Refresh token is expired or wrong | Re-fetch the token from the Aimo web app |
| Setup fails with *"Unable to reach authentication server"* | Network issue | Check HA's internet connectivity |
| Sensor shows `unavailable` after setup | Token expired after a long period without rotation | Re-configure the integration with a fresh token |
| Logs show `Aimo BFF 401 Unauthorized` | Token was rejected by the BFF | Verify the account has access to the configured pool |
