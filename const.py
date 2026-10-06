"""Constants for the Aimo Park integration."""
import datetime

DOMAIN = "aimopark_corporate_pool"

# Config entry keys
CONF_REFRESH_TOKEN = "refresh_token"
CONF_POOL_ID = "pool_id"
CONF_COUNTRY_CODE = "country_code"

# Aimo Park BFF (GraphQL proxy used by the Aimo web/mobile app)
AIMO_BFF_URL = "https://aimoapp-bff.aimopark.io/graphql"
AIMO_TOKEN_URL = (
    "https://account.aimoapp.com/aimoparkextauth.onmicrosoft.com"
    "/b2c_1a_aimo_susi/oauth2/v2.0/token"
)
# Azure B2C app registered for the Aimo self-service web app
AIMO_CLIENT_ID = "aa89a62f-e0f8-42eb-9ceb-4f14801a1204"

# Lists every pooling group the account can use, with live free-space counts
AIMO_READ_PERMITS_QUERY = (
    "query ReadUnifyPermits {\n"
    "  readUnifyPermits {\n"
    "    accessPermitPoolingGroupInfo {\n"
    "      uid\n"
    "      name\n"
    "      freePoolingSpots\n"
    "      poolSize\n"
    "    }\n"
    "  }\n"
    "}"
)

# Polling window boundaries (Helsinki local time, weekdays only)
WINDOW_FAST_START = datetime.time(7, 45)   # inclusive
WINDOW_FAST_END   = datetime.time(9, 15)   # exclusive — fast window ends here
WINDOW_NORMAL_END = datetime.time(13, 0)   # exclusive — normal window ends here

NORMAL_CACHE_TTL      = 300   # seconds  (normal window)
OFFLINE_CACHE_TTL_MIN = 600   # seconds  (outside active hours — lower bound)
OFFLINE_CACHE_TTL_MAX = 1200  # seconds  (outside active hours — upper bound)

# How often HA wakes the coordinator regardless of window.
# The coordinator decides internally whether to hit the API.
COORDINATOR_POLL_INTERVAL = 60  # seconds

HELSINKI_TZ = "Europe/Helsinki"

# Options flow keys (configurable post-setup via Settings → Integrations → Configure)
CONF_WINDOW_BUSY_START    = "window_busy_start"    # str "HH:MM"
CONF_WINDOW_BUSY_END      = "window_busy_end"      # str "HH:MM"
CONF_WINDOW_NORMAL_END    = "window_normal_end"    # str "HH:MM"
CONF_NORMAL_CACHE_TTL     = "normal_cache_ttl"     # int seconds
CONF_OFFLINE_CACHE_TTL_MIN = "offline_cache_ttl_min"  # int seconds
CONF_OFFLINE_CACHE_TTL_MAX = "offline_cache_ttl_max"  # int seconds

# String defaults shown in the options UI
DEFAULT_WINDOW_BUSY_START = "07:45"
DEFAULT_WINDOW_BUSY_END   = "09:15"
DEFAULT_WINDOW_NORMAL_END = "13:00"
