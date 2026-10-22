"""Constants for the Golmar G2Call+ integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "golmar_g2call"
MANUFACTURER: Final = "Golmar/Qualvision"
DEFAULT_NAME: Final = "Golmar G2Call+"
DEFAULT_MODEL: Final = "ART4HW/G2+"

PLATFORMS: Final = ["button", "binary_sensor", "sensor"]

# --- Config entry keys -------------------------------------------------------
CONF_ACCOUNT: Final = "account"
CONF_ACCOUNT_PASSWORD: Final = "account_password"
CONF_DEVICE_UID: Final = "device_uid"
CONF_DEVICE_PASSWORD: Final = "device_password"
CONF_UNLOCK_CODE: Final = "unlock_code"
CONF_HOST: Final = "host"
CONF_PORT: Final = "port"
CONF_SCHEME: Final = "scheme"
CONF_VERIFY_TLS: Final = "verify_tls"
CONF_ENABLE_PORTAL: Final = "enable_portal"
CONF_CLIENT_ID: Final = "client_id"
CONF_REGION_ID: Final = "region_id"
CONF_DOORS: Final = "doors"

# --- Cloud (apertura primaria por OpenAPI) -----------------------------------
CLOUD_OAUTH_HOST: Final = "r1-2.qvcloud.net"
CLOUD_OAUTH_PATH: Final = "/qvoauthv2/token"
CLOUD_API_HOST: Final = "tdkopenapir1.qvcloud.net"
CLOUD_SERVER_INFO_PATH: Final = "/openapi-tdk/client/user/findUserServerInfo"
CLOUD_SYNC_PATH: Final = "/openapi-tdk/devctr/synccontrol/singledev"
CLOUD_OEM_ID: Final = "G0053,A0053"
CLOUD_APP_ID: Final = "4053"
CLOUD_CLIENT_TYPE: Final = "0"
# region_id=0 hangs the backend (validated 2026-10-22); this account lives in
# region 1 (host r1-2 = region 1, server 2).
DEFAULT_REGION_ID: Final = 1
CLOUD_TIMEOUT: Final = 20.0
# Refresh the access token proactively: never wait for a 401.
TOKEN_REFRESH_MARGIN: Final = timedelta(minutes=5)

# --- Local CGI (fallback) ----------------------------------------------------
DEFAULT_CGI_PORT: Final = 443
DEFAULT_CGI_SCHEME: Final = "https"
CGI_PATH: Final = "/tdkcgi"
CGI_TIMEOUT: Final = 8.0
CGI_IDENTIFY_RETRY_DELAY: Final = 1.0
CGI_USERNAME: Final = "admin"

CMD_PRODUCT_INFO: Final = "get.product.info"
CMD_SYSTEM_INFO: Final = "get.system.info"
CMD_ATTACH_INFO: Final = "get.device.attachInfo"
CMD_OPENDOOR: Final = "set.device.opendoor"

# Door/lock map defaults (D3: Portal disabled until validated).
DEFAULT_DOORS: Final = {
    "principal": {"door": 9, "lock": 1, "enabled": True},
    "portal": {"door": 1, "lock": 1, "enabled": False},
}

# --- Runtime -----------------------------------------------------------------
UPDATE_INTERVAL: Final = timedelta(minutes=15)
UNLOCK_RATE_LIMIT: Final = 3.0  # seconds between unlocks, shared cloud/local

# --- CGI protocol result codes (body/error) ---------------------------------
CGI_ERRORS: Final = {
    0: "ok",
    -1: "invalid_envelope",
    -3: "invalid_unlock_code",
    -4: "device_busy",
    -5: "device_locked",
    -6: "channel_disabled",
    -7: "lock_disabled",
    -10: "unknown_command",
    401: "invalid_device_credentials",
}

# --- Cloud OAuth result codes (validated 2026-10-22) ------------------------
OAUTH_RESULT_PASSWORD_ERROR: Final = -20
OAUTH_RESULT_INVALID_CLIENT: Final = -11  # shown as "fail code:100101122"
