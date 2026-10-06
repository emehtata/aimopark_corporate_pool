"""Azure B2C username/password login (authorization code + PKCE) for Aimo Park."""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import re
import secrets
from urllib.parse import parse_qs, urlparse

import aiohttp

from .const import (
    AIMO_AUTH_HOST,
    AIMO_AUTHORIZE_URL,
    AIMO_CLIENT_ID,
    AIMO_REDIRECT_URI,
    AIMO_TOKEN_URL,
)

_SETTINGS_RE = re.compile(r"var SETTINGS = (\{.*?\});\s*\n", re.S)
_TIMEOUT = aiohttp.ClientTimeout(total=15)


class AimoAuthError(Exception):
    """Login failed; `key` is a config-flow error key."""

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def encode_password(password: str) -> str:
    """Obfuscate a password for config-entry storage."""
    return f"base64:{base64.b64encode(password.encode()).decode()}"


async def async_password_login(username: str, password: str) -> dict:
    """Log in and return the token response (access_token, refresh_token, ...)."""
    # Cookies are forwarded by hand in _login: aiohttp's jar re-encodes the B2C cookies and B2C answers 400
    async with aiohttp.ClientSession(cookie_jar=aiohttp.DummyCookieJar()) as session:
        return await _login(session, username, password)


async def _login(session: aiohttp.ClientSession, username: str, password: str) -> dict:
    cookies: dict[str, str] = {}

    def keep_cookies(resp: aiohttp.ClientResponse) -> None:
        for header in resp.headers.getall("Set-Cookie", []):
            name, _, value = header.split(";")[0].partition("=")
            cookies[name] = value

    def cookie_header() -> dict[str, str]:
        return {"Cookie": "; ".join(f"{k}={v}" for k, v in cookies.items())}

    verifier = secrets.token_urlsafe(48)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    scope = f"openid offline_access {AIMO_CLIENT_ID}"

    try:
        async with session.get(
            AIMO_AUTHORIZE_URL,
            params={
                "client_id": AIMO_CLIENT_ID,
                "response_type": "code",
                "redirect_uri": AIMO_REDIRECT_URI,
                "scope": scope,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "state": secrets.token_urlsafe(8),
                "nonce": secrets.token_urlsafe(8),
                "response_mode": "query",
            },
            allow_redirects=False,
            timeout=_TIMEOUT,
        ) as resp:
            page = await resp.text()
            referer = str(resp.url)
            keep_cookies(resp)

        # B2C asks for the e-mail first and the password on a second page
        code = None
        for fields in ({"signInName": username}, {"password": password}):
            settings = json.loads(_SETTINGS_RE.search(page).group(1))
            tenant = settings["hosts"]["tenant"]
            policy = settings["hosts"]["policy"]
            tx, csrf = settings["transId"], settings["csrf"]

            async with session.post(
                f"{AIMO_AUTH_HOST}{tenant}/SelfAsserted",
                params={"tx": tx, "p": policy},
                headers={
                    "X-CSRF-TOKEN": csrf,
                    "X-Requested-With": "XMLHttpRequest",
                    "Referer": referer,
                    **cookie_header(),
                },
                data={"request_type": "RESPONSE", **fields},
                timeout=_TIMEOUT,
            ) as resp:
                result = await resp.json(content_type=None)
                keep_cookies(resp)
            if str(result.get("status")) != "200":
                raise AimoAuthError("invalid_auth")

            async with session.get(
                f"{AIMO_AUTH_HOST}{tenant}/api/{settings['api']}/confirmed",
                params={
                    "rememberMe": "false",
                    "csrf_token": csrf,
                    "tx": tx,
                    "p": policy,
                },
                headers=cookie_header(),
                allow_redirects=False,
                timeout=_TIMEOUT,
            ) as resp:
                location = resp.headers.get("Location", "")
                page = await resp.text()
                keep_cookies(resp)
            if "code=" in location:
                code = parse_qs(urlparse(location).query)["code"][0]
                break

        if code is None:
            raise AimoAuthError("invalid_auth")

        async with session.post(
            AIMO_TOKEN_URL,
            data={
                "grant_type": "authorization_code",
                "client_id": AIMO_CLIENT_ID,
                "code": code,
                "redirect_uri": AIMO_REDIRECT_URI,
                "code_verifier": verifier,
                "scope": scope,
            },
            headers={"Origin": AIMO_REDIRECT_URI.rstrip("/")},
            timeout=_TIMEOUT,
        ) as resp:
            if resp.status != 200:
                raise AimoAuthError("invalid_auth")
            tokens = await resp.json(content_type=None)
    except (aiohttp.ClientError, asyncio.TimeoutError) as err:
        raise AimoAuthError("cannot_connect") from err
    except (AttributeError, KeyError, ValueError) as err:
        # Unknown e-mail or an unexpected page: no usable login form or JSON reply
        raise AimoAuthError("invalid_auth") from err

    if not tokens.get("access_token"):
        raise AimoAuthError("invalid_auth")
    return tokens
