# Aimo Park Corporate Pool — Home Assistant Integration

A custom component that exposes the number of **free parking spaces** in your [Aimo Park](https://aimoapp.aimopark.io/) corporate pooling groups as Home Assistant sensors, one per pool.

## Table of Contents

- [Features](#features)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Authentication](#authentication)
- [How to get the Pool ID (optional)](#how-to-get-the-pool-id-optional)
- [Polling windows](#polling-windows-helsinki-timezone-weekdays-only)
- [Force-refresh service](#force-refresh-service)
- [Sensor attributes](#sensor-attributes)
- [Troubleshooting](#troubleshooting)
- [Glossary](#glossary)

## Features

- **`sensor.<pool_name>_free_spaces`** — real-time free space count, one sensor per pool your account can use (discovered automatically, new pools appear without reconfiguring)
- **Time-windowed polling** — polls more aggressively during the busy morning rush and backs off outside working hours, minimising unnecessary API calls
- **Offline caching** — serves a randomised-TTL cache when outside active polling windows so HA never hits the API needlessly
- **Username/password login** — sign in with your Aimo Park e-mail and password; the integration keeps a rotating refresh token and logs in again by itself if it expires
- **Force-refresh service** — `aimo_park.force_refresh` skips the cache on demand (useful in automations)
- **Configurable windows & TTLs** — all timing thresholds are adjustable after setup via **Settings → Integrations → Aimo Park → Configure**

## Requirements

- Home Assistant with custom components support (e.g. installed via HACS or manually)
- An Aimo Park account with access to at least one corporate pooling group
- The e-mail and password of your Aimo Park account

## Installation

1. Copy the `aimopark_corporate_pool/` folder into your `config/custom_components/` directory.
2. Restart Home Assistant.
3. Go to **Settings → Devices & Services → Add Integration** and search for **Aimo Park Corporate Pool**.

## Configuration

During setup you will be prompted for these values:

| Field | Description |
|---|---|
| **E-mail** | Your Aimo Park account e-mail |
| **Password** | Your Aimo Park account password |
| **Pool ID** | Optional. Leave empty to create a sensor for every pool your account can use; set a `poolingGroupUid` to limit to one (see below) |
| **Country code** | Two-letter country code, e.g. `FI` (default) |
| **Window times and cache TTLs** | Busy/normal window boundaries and cache lifetimes; defaults are listed under [Polling windows](#polling-windows-helsinki-timezone-weekdays-only) |

The credentials are checked against the Aimo login server before the entry is created. If they are wrong or the server is unreachable you will see an error in the setup form.

## Authentication

The integration logs in the same way the Aimo web app does and stores the e-mail, password and the refresh token it receives in the config entry (Home Assistant keeps config entries unencrypted in `.storage`). The refresh token is used for normal operation and renewed automatically; the password is only used to log in again if the refresh token is missing or rejected.

Entries created with version 0.1.0 (refresh token only) keep working. To get the same self-healing login, remove the entry and add it again with your e-mail and password.

## How to get the Pool ID (optional)

Pools are discovered automatically from your account's permits, so this is only needed to limit the integration to one pool.

Every discovered pool's ID is shown in the `pool_id` attribute of its sensor (**Developer Tools → States**). Copy it from there and enter it as the Pool ID when adding the integration again.

Existing entries that were set up with a Pool ID keep working and stay limited to that pool.

## Polling windows (Helsinki timezone, weekdays only)

| Window | Default time range | Behaviour |
|---|---|---|
| **Busy (fast)** | 07:45 – 09:15 | Fetches on every coordinator wake-up (every 60 s) |
| **Normal** | 09:15 – 13:00 | Serves cache up to the normal cache TTL (default 300 s) |
| **Outside hours** | all other times & weekends | Serves cache up to a randomised TTL (default 600 – 1200 s) |

All window boundaries and TTLs can be changed after setup via **Settings → Integrations → Aimo Park → Configure**.

## Force-refresh service

Call `aimopark_corporate_pool.force_refresh` to bypass the cache immediately:

```yaml
service: aimopark_corporate_pool.force_refresh
# Optional: target a specific entry when multiple accounts or pool filters are configured
data:
  entry_id: "<config_entry_id>"
```

## Sensor attributes

| Attribute | Description |
|---|---|
| `pool_id` | The pooling group ID |
| `pool_size` | Total number of spaces in the pool |

The sensor state itself is the number of free spaces (integer).

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| Setup fails with *"Incorrect e-mail or password"* | Wrong credentials | Check that you can log in at aimoapp.aimopark.io with the same e-mail and password |
| Setup fails with *"Unable to reach the Aimo Park login server"* | Network issue | Check HA's internet connectivity |
| Sensor shows `unavailable` and logs show `login failed` | Password was changed or the account is locked | Remove the entry and add it again with the current password |
| Logs show `Aimo BFF 401 Unauthorized` | Token was rejected by the BFF | Verify the account has access to the pools, or to the configured Pool ID |

## Glossary

| Term | Expansion | Description |
|---|---|---|
| **API** | Application Programming Interface | A defined contract that allows two software components to communicate; here refers to the Aimo Park BFF GraphQL endpoint |
| **BFF** | Backend For Frontend | A server-side proxy layer that aggregates backend calls and adapts responses for a specific client; here: Aimo's GraphQL proxy at `aimoapp-bff.aimopark.io` |
| **GraphQL** | Graph Query Language | A query language and runtime for APIs; used as the communication protocol between the Aimo web app and the Aimo BFF |
| **HA** | Home Assistant | The open-source home automation platform this integration runs on |
| **HACS** | Home Assistant Community Store | A community-maintained add-on manager for Home Assistant that simplifies installation of custom integrations and themes |
| **TTL** | Time To Live | The maximum age of a cached value in seconds; once exceeded, a fresh API call is made instead of serving the cached result |
