from __future__ import annotations

import asyncio
import base64
import json
import hashlib
import importlib
from types import SimpleNamespace

import pytest

from custom_components.aimopark_corporate_pool import auth, config_flow, coordinator
integration = importlib.import_module("custom_components.aimopark_corporate_pool")
from custom_components.aimopark_corporate_pool import sensor
from custom_components.aimopark_corporate_pool.const import (
    CONF_OFFLINE_CACHE_TTL_MAX,
    CONF_OFFLINE_CACHE_TTL_MIN,
    CONF_NORMAL_CACHE_TTL,
    CONF_WINDOW_BUSY_END,
    CONF_WINDOW_BUSY_START,
    CONF_WINDOW_NORMAL_END,
    DEFAULT_WINDOW_BUSY_END,
    DEFAULT_WINDOW_BUSY_START,
    DEFAULT_WINDOW_NORMAL_END,
)


class FakeResponse:
    def __init__(self, *, status=200, body=None, headers=None, location=""):
        self.status = status
        self._body = body
        self._headers = headers or []
        self.headers = HeaderMap(location, self._headers)
        self.url = "https://account.aimoapp.com/login"

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def getall(self, name):
        return self._headers if name == "Set-Cookie" else []

    async def text(self):
        if isinstance(self._body, str):
            return self._body
        return json.dumps(self._body)

    async def json(self, content_type=None):
        if isinstance(self._body, str):
            return json.loads(self._body)
        return self._body


class HeaderMap(dict):
    def __init__(self, location, cookies):
        super().__init__()
        if location:
            self["Location"] = location
        self._cookies = cookies

    def getall(self, name, default=None):
        return self._cookies if name == "Set-Cookie" else (default or [])


class AuthSession:
    def __init__(self, *, bad_status=False):
        self.bad_status = bad_status
        self.confirmed = 0
        self.cookies = 0

    def get(self, url, **kwargs):
        if "/confirmed" in url:
            self.confirmed += 1
            if self.confirmed == 2:
                return FakeResponse(
                    location="https://aimoapp.aimopark.io/?code=test-code"
                )
            return FakeResponse(body=_login_page())
        return FakeResponse(body=_login_page(), headers=["session=abc; Path=/"])

    def post(self, url, **kwargs):
        if url.endswith("/token"):
            return FakeResponse(body={"access_token": "access", "refresh_token": "refresh"})
        status = 400 if self.bad_status else 200
        return FakeResponse(status=status, body={"status": str(status)})


def _login_page():
    settings = {
        "hosts": {
            "tenant": "/aimoparkextauth.onmicrosoft.com/B2C_1A_Aimo_Susi",
            "policy": "B2C_1A_Aimo_Susi",
        },
        "transId": "tx",
        "csrf": "csrf",
        "api": "CombinedSigninAndSignup",
    }
    return f"var SETTINGS = {json.dumps(settings)};\n"


def run(coro):
    return asyncio.run(coro)


def test_time_and_password_helpers():
    assert config_flow._time_str("7:5") == "07:05"
    with pytest.raises(ValueError):
        config_flow._time_str("bad")
    encoded = auth.encode_password("sëcret")
    assert encoded == "base64:" + base64.b64encode("sëcret".encode()).decode()


def test_validate_options_defaults_and_ttl_error():
    values = {
        CONF_WINDOW_BUSY_START: DEFAULT_WINDOW_BUSY_START,
        CONF_WINDOW_BUSY_END: DEFAULT_WINDOW_BUSY_END,
        CONF_WINDOW_NORMAL_END: DEFAULT_WINDOW_NORMAL_END,
        CONF_OFFLINE_CACHE_TTL_MIN: 600,
        CONF_OFFLINE_CACHE_TTL_MAX: 1200,
    }
    assert config_flow._validate_options(values) == {}
    assert values[CONF_WINDOW_BUSY_START] == "07:45"
    values[CONF_OFFLINE_CACHE_TTL_MIN] = 1200
    assert config_flow._validate_options(values)[CONF_OFFLINE_CACHE_TTL_MIN] == "ttl_min_gte_max"


def test_validate_options_reports_missing_or_bad_times():
    values = {CONF_WINDOW_BUSY_START: "bad", CONF_WINDOW_BUSY_END: "09:15"}
    errors = config_flow._validate_options(values)
    assert errors[CONF_WINDOW_BUSY_START] == "invalid_time"
    assert errors[CONF_WINDOW_NORMAL_END] == "invalid_time"


def test_password_login_success_and_failure():
    session = AuthSession()
    result = run(auth._login(session, "user@example.com", "password"))
    assert result["access_token"] == "access"
    assert result["refresh_token"] == "refresh"

    with pytest.raises(auth.AimoAuthError) as error:
        run(auth._login(AuthSession(bad_status=True), "user@example.com", "password"))
    assert error.value.key == "invalid_auth"


def test_password_login_rejects_unexpected_login_page():
    session = AuthSession()
    session.get = lambda url, **kwargs: FakeResponse(body="not a login page")
    with pytest.raises(auth.AimoAuthError) as error:
        run(auth._login(session, "user@example.com", "password"))
    assert error.value.key == "invalid_auth"


def test_refresh_token_validation(monkeypatch):
    class Session:
        def post(self, *args, **kwargs):
            return FakeResponse(body={"access_token": "access"})

    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda hass: Session())
    error, account = run(config_flow._validate_refresh_token(object(), "refresh"))
    assert error is None
    assert account == __import__("hashlib").sha256(b"refresh").hexdigest()


class FakeEntry:
    def __init__(self, data=None, options=None):
        self.data = data or {}
        self.options = options or {}


def coordinator_for(pool_id=None, options=None):
    instance = object.__new__(coordinator.AimoParkCoordinator)
    instance.hass = object()
    instance._entry = FakeEntry(
        {"pool_id": pool_id or "", "country_code": "FI"}, options
    )
    instance._access_token = "access"
    instance._token_expires_at = 10**20
    instance._result_cache = None
    instance._result_fetched_at = 0
    instance._offline_ttl = 600
    instance._force_next = False
    instance._auth_retry_at = 0
    return instance


def test_coordinator_windows_and_password_decoding():
    instance = coordinator_for(options={CONF_WINDOW_BUSY_START: "bad"})
    assert instance._get_window_time(CONF_WINDOW_BUSY_START, DEFAULT_WINDOW_BUSY_START) == DEFAULT_WINDOW_BUSY_START
    assert instance._decode_password("base64:c2VjcmV0") == "secret"
    assert instance._decode_password("legacy") == "legacy"
    assert instance._decode_password("base64:?") == ""
    assert instance.pool_filter is None
    assert instance.country_code == "FI"


def test_fetch_pools_deduplicates_and_filters(monkeypatch):
    instance = coordinator_for(pool_id="pool-2")
    payload = {
        "data": {
            "readUnifyPermits": [
                {"accessPermitPoolingGroupInfo": [
                    {"uid": "pool-1", "name": "One", "freePoolingSpots": 1, "poolSize": 2},
                    {"uid": "pool-2", "name": "Two", "freePoolingSpots": 3, "poolSize": 4},
                ]},
                {"accessPermitPoolingGroupInfo": [
                    {"uid": "pool-2", "name": "Two", "freePoolingSpots": 5, "poolSize": 4},
                ]},
            ]
        }
    }

    class Session:
        def post(self, *args, **kwargs):
            return FakeResponse(body=payload)

    monkeypatch.setattr(coordinator, "async_get_clientsession", lambda hass: Session())
    result = run(instance._fetch_pools())
    assert result == {"pools": {"pool-2": {"name": "Two", "free": 5, "size": 4}}}


def test_fetch_pools_reports_graphql_and_shape_errors(monkeypatch):
    instance = coordinator_for()

    class Session:
        def __init__(self, body):
            self.body = body

        def post(self, *args, **kwargs):
            return FakeResponse(body=self.body)

    monkeypatch.setattr(
        coordinator,
        "async_get_clientsession",
        lambda hass: Session({"errors": [{"extensions": {"code": "BAD"}}]}),
    )
    with pytest.raises(coordinator.UpdateFailed):
        run(instance._fetch_pools())

    monkeypatch.setattr(
        coordinator,
        "async_get_clientsession",
        lambda hass: Session({"data": {}}),
    )
    with pytest.raises(coordinator.UpdateFailed):
        run(instance._fetch_pools())


def test_coordinator_cache_and_force_refresh(monkeypatch):
    instance = coordinator_for()
    instance._poll_window = lambda: "normal"
    instance._result_cache = {"pools": {}}
    instance._result_fetched_at = __import__("time").monotonic()
    instance._entry.options = {"normal_cache_ttl": 300}
    calls = []

    async def fetch():
        calls.append(True)
        return {"pools": {"new": {}}}

    instance._fetch_pools = fetch
    assert run(instance._async_update_data()) == {"pools": {}}
    instance.request_force_refresh()
    assert run(instance._async_update_data()) == {"pools": {"new": {}}}
    assert len(calls) == 1


def test_jwt_and_poll_windows(monkeypatch):
    payload = base64.urlsafe_b64encode(json.dumps({"sub": "user"}).encode()).rstrip(b"=").decode()
    assert coordinator.AimoParkCoordinator._decode_jwt_claims(f"x.{payload}.y")["sub"] == "user"
    assert coordinator.AimoParkCoordinator._decode_jwt_claims("bad") == {}
    instance = coordinator_for()
    monkeypatch.setattr(coordinator.datetime, "datetime", SimpleNamespace(
        now=lambda _tz: SimpleNamespace(weekday=lambda: 5, time=lambda: __import__("datetime").time(8)),
    ))
    assert instance._poll_window() is None


def test_refresh_grant_and_token_refresh(monkeypatch):
    instance = coordinator_for()
    instance._entry.data["refresh_token"] = "old"
    instance.hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=lambda *args, **kwargs: None))

    class Session:
        def post(self, *args, **kwargs):
            return FakeResponse(body={"access_token": "new", "refresh_token": "rotated", "expires_in": 100})

    monkeypatch.setattr(coordinator, "async_get_clientsession", lambda hass: Session())
    assert run(instance._request_refresh_grant("old"))["access_token"] == "new"
    assert run(instance._refresh_access_token()) == "new"
    assert instance._access_token == "new"


def test_refresh_falls_back_to_password_and_cools_down(monkeypatch):
    instance = coordinator_for()
    instance._entry.data = {"username": "u", "password": "legacy"}
    instance.hass = SimpleNamespace(config_entries=SimpleNamespace(async_update_entry=lambda *args, **kwargs: None))
    async def login(username, password):
        return {"access_token": "password-token", "refresh_token": "rt"}
    monkeypatch.setattr(coordinator, "async_password_login", login)
    assert run(instance._refresh_access_token()) == "password-token"
    instance._entry.data = {}
    with pytest.raises(coordinator.ConfigEntryAuthFailed):
        run(instance._refresh_access_token())
    assert instance._auth_retry_at > 0
    with pytest.raises(coordinator.ConfigEntryAuthFailed):
        run(instance._refresh_access_token())


def test_sensor_properties_and_dynamic_setup():
    data = {"pools": {"p1": {"name": "Garage", "free": 7, "size": 20}}}
    instance = SimpleNamespace(data=data, last_update_success=True, async_add_listener=lambda callback: lambda: None)
    entity = sensor.AimoParkFreeSpacesSensor(instance, "p1")
    assert entity.native_value == 7
    assert entity.available is True
    assert entity.device_info["name"] == "Garage"
    assert entity.extra_state_attributes["pool_size"] == 20
    instance.data = {"pools": {}}
    assert entity.native_value is None
    assert entity.available is False


def test_config_flow_setup_and_reauth_paths(monkeypatch):
    flow = config_flow.AimoParkConfigFlow()
    flow.hass = object()
    monkeypatch.setattr(config_flow, "_validate_refresh_token", lambda hass, token: asyncio.sleep(0, result=(None, "account")))
    flow.async_show_form = lambda **kwargs: kwargs
    flow.async_create_entry = lambda **kwargs: kwargs
    flow.async_set_unique_id = lambda value: asyncio.sleep(0)
    flow._abort_if_unique_id_configured = lambda: None
    base = {
        "username": "", "password": "", "refresh_token": "rt", "pool_id": "p",
        "country_code": "FI", CONF_WINDOW_BUSY_START: "07:45", CONF_WINDOW_BUSY_END: "09:15",
        CONF_WINDOW_NORMAL_END: "13:00", CONF_NORMAL_CACHE_TTL: 300,
        CONF_OFFLINE_CACHE_TTL_MIN: 600, CONF_OFFLINE_CACHE_TTL_MAX: 1200,
    }
    result = run(flow.async_step_user(base))
    assert result["title"] == "Aimo Park (p)"
    assert result["data"]["refresh_token"] == "rt"
    result = run(flow.async_step_user({**base, "refresh_token": "", "username": "u"}))
    assert result["errors"]["base"] == "auth_method_required"

    flow.context = {"entry_id": "e"}
    entry = SimpleNamespace(data={"pool_id": "p"})
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_entry=lambda _: entry))
    flow.async_update_reload_and_abort = lambda entry, **kwargs: kwargs
    monkeypatch.setattr(config_flow, "async_password_login", lambda u, p: asyncio.sleep(0, result={"refresh_token": "new"}))
    result = run(flow.async_step_reauth({"username": "u", "password": "p", "refresh_token": ""}))
    assert result["reason"] == "reauth_successful"


def test_config_flow_refresh_token_errors(monkeypatch):
    class Session:
        def post(self, *args, **kwargs):
            return FakeResponse(status=401, body={})
    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda hass: Session())
    assert run(config_flow._validate_refresh_token(object(), "bad")) == ("invalid_auth", None)

    class BrokenSession:
        def post(self, *args, **kwargs):
            raise __import__("aiohttp").ClientError()
    monkeypatch.setattr(config_flow, "async_get_clientsession", lambda hass: BrokenSession())
    assert run(config_flow._validate_refresh_token(object(), "bad")) == ("cannot_connect", None)


def test_options_flow_and_sensor_setup():
    entry = SimpleNamespace(options={})
    options = config_flow.AimoParkOptionsFlow(entry)
    options.async_show_form = lambda **kwargs: kwargs
    options.async_create_entry = lambda **kwargs: kwargs
    shown = run(options.async_step_init({CONF_WINDOW_BUSY_START: "bad"}))
    assert shown["errors"][CONF_WINDOW_BUSY_START] == "invalid_time"
    created = run(options.async_step_init({
        CONF_WINDOW_BUSY_START: "07:45", CONF_WINDOW_BUSY_END: "09:15",
        CONF_WINDOW_NORMAL_END: "13:00", CONF_OFFLINE_CACHE_TTL_MIN: 600,
        CONF_OFFLINE_CACHE_TTL_MAX: 1200,
    }))
    assert created["data"][CONF_WINDOW_BUSY_START] == "07:45"

    added = []
    callback_holder = []
    coordinator_instance = SimpleNamespace(
        data={"pools": {"b": {"name": "B"}, "a": {"name": "A"}}},
        async_add_listener=lambda callback: callback_holder.append(callback) or (lambda: None),
    )
    hass = SimpleNamespace(data={"aimopark_corporate_pool": {"entry": coordinator_instance}})
    sensor_entry = SimpleNamespace(entry_id="entry", async_on_unload=lambda remove: None)
    run(sensor.async_setup_entry(hass, sensor_entry, lambda entities: added.extend(entities)))
    assert [entity._pool_id for entity in added] == ["a", "b"]


def test_coordinator_http_errors_and_auth_graphql(monkeypatch):
    instance = coordinator_for()
    instance._access_token = "access"
    instance._token_expires_at = 10**20
    class Session:
        def __init__(self, status, body): self.status, self.body = status, body
        def post(self, *args, **kwargs): return FakeResponse(status=self.status, body=self.body)
    for status in (401, 500):
        instance._access_token = "access"
        instance._token_expires_at = 10**20
        monkeypatch.setattr(coordinator, "async_get_clientsession", lambda hass, s=Session(status, "error"): s)
        with pytest.raises(coordinator.UpdateFailed): run(instance._fetch_pools())
    monkeypatch.setattr(coordinator, "async_get_clientsession", lambda hass: Session(200, {"errors": [{"extensions": {"code": "UNAUTHENTICATED"}}]}))
    with pytest.raises(coordinator.UpdateFailed): run(instance._fetch_pools())
    assert instance._access_token is None


def test_coordinator_cached_token_windows_and_failed_grant(monkeypatch):
    instance = coordinator_for(options={CONF_NORMAL_CACHE_TTL: 300})
    instance._access_token = "cached"
    instance._token_expires_at = 10**20
    assert run(instance._get_access_token()) == "cached"
    assert instance._get_window_time(CONF_WINDOW_BUSY_START, __import__("datetime").time(7, 45))
    instance._result_cache = {"pools": {}}
    instance._result_fetched_at = __import__("time").monotonic()
    instance._poll_window = lambda: "normal"
    async def fail_fetch(): raise AssertionError("cache should be used")
    instance._fetch_pools = fail_fetch
    assert run(instance._async_update_data()) == {"pools": {}}

    class Session:
        def post(self, *args, **kwargs): return FakeResponse(status=500, body="failed")
    monkeypatch.setattr(coordinator, "async_get_clientsession", lambda hass: Session())
    assert run(instance._request_refresh_grant("bad")) is None


def test_flow_initial_form_and_unknown_reauth():
    flow = config_flow.AimoParkConfigFlow()
    flow.async_show_form = lambda **kwargs: kwargs
    assert run(flow.async_step_user())['step_id'] == 'user'
    flow.context = {"entry_id": "missing"}
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_entry=lambda _: None))
    assert run(flow.async_step_reauth())['reason'] == 'unknown_error'


def test_poll_window_fast_normal_and_closed(monkeypatch):
    instance = coordinator_for()
    date_module = __import__("datetime")
    for clock, expected in ((date_module.time(8), "fast"), (date_module.time(10), "normal"), (date_module.time(14), None)):
        class Clock:
            @staticmethod
            def now(_tz):
                return SimpleNamespace(weekday=lambda: 2, time=lambda: clock)
        monkeypatch.setattr(coordinator.datetime, "datetime", Clock)
        assert instance._poll_window() == expected


def test_reauth_validation_errors_and_options_ttl():
    flow = config_flow.AimoParkConfigFlow()
    flow.hass = SimpleNamespace(config_entries=SimpleNamespace(async_get_entry=lambda _: SimpleNamespace(data={})))
    flow.context = {"entry_id": "entry"}
    flow.async_show_form = lambda **kwargs: kwargs
    result = run(flow.async_step_reauth({"username": "u", "password": "", "refresh_token": ""}))
    assert result["errors"]["base"] == "auth_method_required"
    options = config_flow.AimoParkOptionsFlow(SimpleNamespace(options={}))
    options.async_show_form = lambda **kwargs: kwargs
    result = run(options.async_step_init({
        CONF_WINDOW_BUSY_START: "07:45", CONF_WINDOW_BUSY_END: "09:15",
        CONF_WINDOW_NORMAL_END: "13:00", CONF_OFFLINE_CACHE_TTL_MIN: 1200,
        CONF_OFFLINE_CACHE_TTL_MAX: 600,
    }))
    assert result["errors"][CONF_OFFLINE_CACHE_TTL_MIN] == "ttl_min_gte_max"


def test_integration_setup_unload(monkeypatch):
    class FakeCoordinator:
        def __init__(self, hass, entry): self.entry = entry
        async def async_config_entry_first_refresh(self): pass
        def request_force_refresh(self): self.forced = True
        async def async_refresh(self): pass
    class Services:
        def __init__(self): self.handlers = {}; self.removed = False
        def has_service(self, domain, name): return name in self.handlers
        def async_register(self, domain, name, handler, schema=None): self.handlers[name] = handler
        def async_remove(self, domain, name): self.removed = True
    services = Services()
    entry = SimpleNamespace(entry_id="id")
    config_entries = SimpleNamespace(async_forward_entry_setups=lambda *args: asyncio.sleep(0), async_unload_platforms=lambda *args: asyncio.sleep(0, result=True))
    hass = SimpleNamespace(data={}, services=services, config_entries=config_entries)
    monkeypatch.setattr(integration, "AimoParkCoordinator", FakeCoordinator)
    assert run(integration.async_setup_entry(hass, entry)) is True
    assert "force_refresh" in services.handlers
    run(services.handlers["force_refresh"](SimpleNamespace(data={})))
    assert run(integration.async_unload_entry(hass, entry)) is True
    assert services.removed is True
