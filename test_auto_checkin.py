import importlib.util
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest


SCRIPT_PATH = Path(__file__).resolve().parent / "auto_checkin.py"


def load_module():
    spec = importlib.util.spec_from_file_location("auto_checkin", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_decrypts_sxsx_payload_from_har_upload_response():
    module = load_module()
    encrypted = (
        "OFjsidnGz1RLZuOnPqUI6BJMYmdxPj32wSO3fhnWkncBuub+ualG1gyixLVfIDjQwbtLi0q/"
        "x0O/J6P70y2sAEO1ecca38p2utgIRNs92SOt5Kwh0ULHNRI6tsmCYL8kRk/xUAZhMFFYZoQG0"
        "TlyJ1wfqz/5ZHBpaeRU3zLljqN0QOD/bbhjXRii1+rmOHNWWvXusoNSVcWkFvqNcYBIwVrMTeu"
        "U6/ZRV5Orlh/bsr4kIzVe5fKFz3LOtSFJN0gKghzvJ1967zekBF8i2QQ0l4QpdwJ9/g39wAI4"
        "aIvfMWwPgOjCSfc4gg+sRy10oEJiIbfUUJpxhcLxmf2VL0Wu+0IJzZxbIaB+s9LBg7urbtQru"
        "2PWVrEi/iHt1z78BB5orHJvbHKJYvvJ0iQRFm9I6uFfIbGOjQeRmYszzyhmg0zkwx3VdmnMsB"
        "mfGaDmtGsnguY26ug5b1bKIhTSQl4Zj3QafTG9uEdcLkYOYCDqDnkUjG4ygW7KqhKebOdM1Lb"
        "ZchRpu9evUe8xvcOeJeocySOdTwSUqgtJwvIwTV+rfeMp5z/jAZ4Ud6jjUHCN5tqXWrFwQvEQ"
        "XwR6cpGDIF62sgrRS2EBQ5J9ZuHbKsgNIkY="
    )

    data = module.decrypt_sxsx_data(encrypted)

    assert data["remark"] == "/file6/upload/2026/04/23/d05e76dc037e43fd95da52bd301a8058.png"


def test_extract_upload_remark_from_encrypted_response():
    module = load_module()
    encrypted = (
        "OFjsidnGz1RLZuOnPqUI6BJMYmdxPj32wSO3fhnWkncBuub+ualG1gyixLVfIDjQwbtLi0q/"
        "x0O/J6P70y2sAEO1ecca38p2utgIRNs92SOt5Kwh0ULHNRI6tsmCYL8kRk/xUAZhMFFYZoQG0"
        "TlyJ1wfqz/5ZHBpaeRU3zLljqN0QOD/bbhjXRii1+rmOHNWWvXusoNSVcWkFvqNcYBIwVrMTeu"
        "U6/ZRV5Orlh/bsr4kIzVe5fKFz3LOtSFJN0gKghzvJ1967zekBF8i2QQ0l4QpdwJ9/g39wAI4"
        "aIvfMWwPgOjCSfc4gg+sRy10oEJiIbfUUJpxhcLxmf2VL0Wu+0IJzZxbIaB+s9LBg7urbtQru"
        "2PWVrEi/iHt1z78BB5orHJvbHKJYvvJ0iQRFm9I6uFfIbGOjQeRmYszzyhmg0zkwx3VdmnMsB"
        "mfGaDmtGsnguY26ug5b1bKIhTSQl4Zj3QafTG9uEdcLkYOYCDqDnkUjG4ygW7KqhKebOdM1Lb"
        "ZchRpu9evUe8xvcOeJeocySOdTwSUqgtJwvIwTV+rfeMp5z/jAZ4Ud6jjUHCN5tqXWrFwQvEQ"
        "XwR6cpGDIF62sgrRS2EBQ5J9ZuHbKsgNIkY="
    )
    response = {"code": 200, "needDe": True, "data": encrypted}

    assert module.extract_upload_remark(response) == "/file6/upload/2026/04/23/d05e76dc037e43fd95da52bd301a8058.png"


def test_slot_duplicate_detection_uses_time_window():
    module = load_module()
    clocks = [
        {"clockTime": "2026-04-23 08:03:10"},
        {"clockTime": "2026-04-23 19:01:10"},
    ]

    assert module.has_clock_in_slot(clocks, {"start_hour": 0, "end_hour": 12})
    assert module.has_clock_in_slot(clocks, {"start_hour": 12, "end_hour": 24})
    assert not module.has_clock_in_slot(clocks, {"start_hour": 9, "end_hour": 18})


def test_evening_slot_allows_second_checkin_when_only_one_record_exists():
    module = load_module()

    assert not module.should_skip_existing_checkin(
        [{"clockTime": "2026-04-23 19:01:10"}],
        {"name": "evening", "start_hour": 12, "end_hour": 24},
        skip_if_already_signed=True,
        force=False,
    )


def test_evening_slot_still_skips_when_two_records_already_exist():
    module = load_module()

    assert module.should_skip_existing_checkin(
        [
            {"clockTime": "2026-04-23 08:03:10"},
            {"clockTime": "2026-04-23 19:01:10"},
        ],
        {"name": "evening", "start_hour": 12, "end_hour": 24},
        skip_if_already_signed=True,
        force=False,
    )


def test_pick_slot_for_datetime():
    module = load_module()
    slots = [
        {"name": "morning", "time": "08:05", "start_hour": 0, "end_hour": 12},
        {"name": "evening", "time": "19:05", "start_hour": 12, "end_hour": 24},
    ]

    assert module.pick_slot(datetime(2026, 4, 23, 8, 30), slots)["name"] == "morning"
    assert module.pick_slot(datetime(2026, 4, 23, 19, 30), slots)["name"] == "evening"


def test_iter_account_configs_merges_global_defaults_and_filters_account():
    module = load_module()
    config = {
        "sxsx_base_url": "https://example.test",
        "request_timeout": 9,
        "slots": [{"name": "morning", "time": "08:05", "start_hour": 0, "end_hour": 12}],
        "accounts": [
            {"name": "a", "app_user_id": "100", "nick_name": "A", "proof_image_path": "a.jpg"},
            {"name": "b", "app_user_id": "200", "nick_name": "B", "proof_image_path": "b.jpg"},
        ],
    }

    accounts = list(module.iter_account_configs(config, selected_account="b"))

    assert len(accounts) == 1
    assert accounts[0]["name"] == "b"
    assert accounts[0]["request_timeout"] == 9
    assert accounts[0]["sxsx_base_url"] == "https://example.test"
    assert accounts[0]["proof_image_path"] == "b.jpg"


def test_default_token_file_is_per_account():
    module = load_module()

    assert module.token_file_for_account({"name": "default"}).name == "token.json"
    assert module.token_file_for_account({"name": "student-a"}).name == "token.student-a.json"
    assert module.token_file_for_account({"name": "student/a"}).name == "token.student-a.json"


def test_wait_for_uploaded_image_retries_until_accessible(monkeypatch):
    module = load_module()
    attempts = []

    class Response:
        def __init__(self, status_code, content_type):
            self.status_code = status_code
            self.headers = {"content-type": content_type}

        def close(self):
            pass

    class Session:
        def get(self, url, **kwargs):
            attempts.append((url, kwargs))
            if len(attempts) == 1:
                return Response(404, "text/plain")
            return Response(200, "image/png")

    monkeypatch.setattr(module.time, "sleep", lambda _seconds: None)
    config = {
        "sxsx_base_url": "https://sxsx.example",
        "verify_uploaded_image_timeout": 5,
        "verify_uploaded_image_interval": 1,
    }

    assert module.wait_for_uploaded_image(config, "/file6/upload/a.png", Session())
    assert len(attempts) == 2
    assert attempts[0][0] == "https://sxsx.example/file6/upload/a.png"


def test_image_path_for_slot_prefers_slot_specific_proof_image():
    module = load_module()
    config = {
        "proof_image_path": "proof.jpg",
        "proof_images": {
            "morning": "proof_morning.jpg",
            "evening": "proof_evening.jpg",
        },
    }

    assert module.image_path_for_slot(config, {"name": "morning"}).name == "proof_morning.jpg"
    assert module.image_path_for_slot(config, {"name": "evening"}).name == "proof_evening.jpg"
    assert module.image_path_for_slot(config, {"name": "other"}).name == "proof.jpg"

def test_get_bearer_token_prefers_app_user_id_before_direct_login(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "load_token_cache", lambda _path: {})
    monkeypatch.setattr(module, "fetch_sxsx_bearer_token", lambda config, session: "APP_USER_TOKEN")
    config = {"login_account": "u", "login_password": "p", "app_user_id": "100"}

    token = module.get_bearer_token(config, object())

    assert token == "APP_USER_TOKEN"


def test_get_bearer_token_prefers_cached_token_before_login(monkeypatch):
    module = load_module()
    populate_calls = []
    monkeypatch.setattr(module, "load_token_cache", lambda _path: {"sxsx_bearer_token": "CACHED"})
    monkeypatch.setattr(module, "populate_runtime_config", lambda config, token, session, user_info=None: populate_calls.append(token))

    token = module.get_bearer_token({"login_account": "u", "login_password": "p"}, object())

    assert token == "CACHED"
    assert populate_calls == ["CACHED"]


def test_get_bearer_token_relogins_when_cached_token_invalid(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "load_token_cache", lambda _path: {"sxsx_bearer_token": "BAD"})

    def fail_populate(config, token, session, user_info=None):
        raise module.CheckinError("invalid token")

    monkeypatch.setattr(module, "populate_runtime_config", fail_populate)
    monkeypatch.setattr(module, "fetch_sxsx_bearer_token", lambda config, session: "NEW")

    token = module.get_bearer_token({"login_account": "u", "login_password": "p", "app_user_id": "100"}, object())

    assert token == "NEW"


def test_get_bearer_token_explains_why_password_login_is_unavailable(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "load_token_cache", lambda _path: {})

    with pytest.raises(module.CheckinError) as exc_info:
        module.get_bearer_token({"login_account": "u", "login_password": "p"}, object())

    assert "app_user_id" in str(exc_info.value)
    assert "验证码" in str(exc_info.value)


def test_get_bearer_token_falls_back_to_manual_token(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "fetch_sxsx_bearer_token", lambda config, session: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(module, "load_token_cache", lambda _path=None: {})
    monkeypatch.setattr(module, "populate_runtime_config", lambda config, token, session, user_info=None: None)
    config = {"manual_bearer_token": "MANUAL_TOKEN"}

    token = module.get_bearer_token(config, object())

    assert token == "MANUAL_TOKEN"


def test_populate_runtime_config_rejects_stale_autonomy_id_when_plan_missing(monkeypatch):
    module = load_module()
    config = {"app_user_id": "new-app", "user_id": "old-user", "nick_name": "", "autonomy_id": "old-plan"}

    monkeypatch.setattr(module, "fetch_user_info", lambda config, token, session: {"userId": "new-user", "nickName": "新用户"})
    monkeypatch.setattr(module, "fetch_student_plan", lambda config, token, session: {})

    with pytest.raises(module.CheckinError) as exc_info:
        module.populate_runtime_config(config, "TOKEN", object())

    assert "未查询到可用实习计划" in str(exc_info.value)
    assert config["autonomy_id"] == ""


def test_populate_runtime_config_accepts_practice_plan(monkeypatch):
    module = load_module()
    config = {"app_user_id": "new-app", "user_id": "", "nick_name": "", "autonomy_id": ""}

    monkeypatch.setattr(
        module,
        "fetch_user_info",
        lambda config, token, session: {"userId": "user-1", "userName": "student-name", "nickName": "学生"},
    )
    monkeypatch.setattr(
        module,
        "fetch_student_plan",
        lambda config, token, session: {"practicePlan": {"planId": "plan-1", "planName": "普通实习计划"}},
    )

    module.populate_runtime_config(config, "TOKEN", object())

    assert config["plan_type"] == "practicePlan"
    assert config["practice_plan_id"] == "plan-1"
    assert config["user_id"] == "user-1"
    assert config["user_name"] == "student-name"
    assert config["nick_name"] == "学生"


def test_apply_account_updates_updates_root_config():
    module = load_module()
    config = {"app_user_id": "", "user_id": "", "nick_name": "", "autonomy_id": ""}

    module.apply_account_updates(
        config,
        {"app_user_id": "100", "user_id": "u1", "nick_name": "Nick", "autonomy_id": "a1"},
        account_name=None,
    )

    assert config["app_user_id"] == "100"
    assert config["user_id"] == "u1"
    assert config["nick_name"] == "Nick"
    assert config["autonomy_id"] == "a1"


def test_apply_account_updates_updates_named_account():
    module = load_module()
    config = {
        "accounts": [
            {"name": "a", "app_user_id": ""},
            {"name": "b", "app_user_id": ""},
        ]
    }

    module.apply_account_updates(config, {"app_user_id": "200", "nick_name": "B"}, account_name="b")

    assert config["accounts"][0]["app_user_id"] == ""
    assert config["accounts"][1]["app_user_id"] == "200"
    assert config["accounts"][1]["nick_name"] == "B"


def test_prepare_bind_setup_updates_geocodes_address_and_images(monkeypatch):
    module = load_module()
    monkeypatch.setattr(module, "geocode_address_to_gcj02", lambda address, session=None: (115.1, 28.2))
    monkeypatch.setattr(module, "validate_image_source", lambda path_value: None)
    account_config = {
        "clock_address": "旧地址",
        "proof_image_path": "old.jpg",
        "proof_images": {"morning": "m-old.jpg", "evening": "e-old.jpg"},
    }

    updates = module.prepare_bind_setup_updates(
        account_config,
        address="新地址",
        default_image="proof.jpg",
        morning_image="morning.jpg",
        evening_image="evening.jpg",
    )

    assert updates["clock_address"] == "新地址"
    assert updates["lng"] == 115.1
    assert updates["lat"] == 28.2
    assert updates["proof_image_path"] == "proof.jpg"
    assert updates["proof_images"] == {"morning": "morning.jpg", "evening": "evening.jpg"}


def test_geocode_address_to_gcj02_retries_with_inferred_province(monkeypatch):
    module = load_module()
    responses = [
        [],
        [{"display_name": "鄞州区, 宁波市, 浙江省, 中国", "lon": "121.6", "lat": "29.8"}],
        [{"display_name": "马山村, 鄞州区, 宁波市, 浙江省, 中国", "lon": "121.6674974", "lat": "29.7430841"}],
    ]
    queries = []

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Session:
        def get(self, url, params=None, **kwargs):
            queries.append(params["q"])
            return Response(responses.pop(0))

    monkeypatch.setattr(module, "wgs84_to_gcj02", lambda lng, lat: (lng, lat))

    lng, lat = module.geocode_address_to_gcj02("宁波市鄞州区韩岭村", session=Session())

    assert (lng, lat) == (121.6674974, 29.7430841)
    assert queries == [
        "宁波市鄞州区韩岭村",
        "宁波市鄞州区",
        "浙江省宁波市鄞州区韩岭村",
    ]


def test_geocode_address_to_gcj02_falls_back_to_parent_region():
    module = load_module()
    responses = [
        [],
        [{"display_name": "鄞州区, 宁波市, 浙江省, 中国", "lon": "121.6", "lat": "29.8"}],
        [],
    ]

    class Response:
        def __init__(self, payload):
            self.payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self.payload

    class Session:
        def get(self, url, params=None, **kwargs):
            return Response(responses.pop(0))

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(module, "wgs84_to_gcj02", lambda lng, lat: (lng, lat))
    try:
        lng, lat = module.geocode_address_to_gcj02("宁波市鄞州区韩岭村", session=Session())
    finally:
        monkeypatch.undo()

    assert (lng, lat) == (121.6, 29.8)


def test_bind_account_updates_config_and_saves(monkeypatch):
    module = load_module()
    raw_config = {"accounts": [{"name": "default", "app_user_id": ""}]}
    saved = []
    order = []

    monkeypatch.setattr(
        module,
        "prompt_bind_setup",
        lambda account_config: order.append("prompt") or {"clock_address": "地址", "lng": 1.0, "lat": 2.0},
    )

    monkeypatch.setattr(
        module,
        "interactive_auth_login",
        lambda timeout_seconds=300: order.append("login") or {"auth_token": "AUTH", "cookies": {"token": "AUTH"}},
    )
    monkeypatch.setattr(
        module,
        "fetch_auth_current_user",
        lambda auth_state, session=None: {"id": "1500", "nickName": "测试用户"},
    )

    def fake_fetch_sxsx_bearer_token(config, session=None):
        config["user_id"] = "user-1"
        config["nick_name"] = "测试用户"
        config["autonomy_id"] = "auto-1"
        config["manual_bearer_token"] = "BEARER"
        return "BEARER"

    monkeypatch.setattr(module, "fetch_sxsx_bearer_token", fake_fetch_sxsx_bearer_token)
    monkeypatch.setattr(module, "save_config", lambda config, config_path: saved.append((config_path, config)))

    result = module.bind_account(raw_config, config_path=Path("E:/checkin_config.json"))

    assert result["app_user_id"] == "1500"
    assert result["bearer_token"] == "BEARER"
    assert raw_config["accounts"][0]["app_user_id"] == "1500"
    assert raw_config["accounts"][0]["clock_address"] == "地址"
    assert raw_config["accounts"][0]["manual_bearer_token"] == "BEARER"
    assert raw_config["accounts"][0]["user_id"] == "user-1"
    assert raw_config["accounts"][0]["autonomy_id"] == "auto-1"
    assert order == ["prompt", "login"]
    assert len(saved) == 3
    assert saved[0][0] == Path("E:/checkin_config.json")


def test_bind_account_clears_stale_identity_fields_before_token_exchange(monkeypatch):
    module = load_module()
    raw_config = {
        "accounts": [
            {
                "name": "default",
                "app_user_id": "old-app",
                "manual_bearer_token": "OLD_TOKEN",
                "user_id": "old-user",
                "nick_name": "旧用户",
                "autonomy_id": "old-plan",
            }
        ]
    }
    seen = {}

    monkeypatch.setattr(module, "prompt_bind_setup", lambda account_config: {})
    monkeypatch.setattr(module, "interactive_auth_login", lambda timeout_seconds=300: {"auth_token": "AUTH"})
    monkeypatch.setattr(module, "fetch_auth_current_user", lambda auth_state, session=None: {"id": "new-app"})

    def fake_fetch_sxsx_bearer_token(config, session=None):
        seen.update(
            {
                "app_user_id": config.get("app_user_id"),
                "manual_bearer_token": config.get("manual_bearer_token"),
                "user_id": config.get("user_id"),
                "nick_name": config.get("nick_name"),
                "autonomy_id": config.get("autonomy_id"),
            }
        )
        config["manual_bearer_token"] = "NEW_TOKEN"
        config["user_id"] = "new-user"
        config["nick_name"] = "新用户"
        config["autonomy_id"] = "new-plan"
        return "NEW_TOKEN"

    monkeypatch.setattr(module, "fetch_sxsx_bearer_token", fake_fetch_sxsx_bearer_token)
    monkeypatch.setattr(module, "save_config", lambda config, config_path: None)

    module.bind_account(raw_config, config_path=Path("E:/checkin_config.json"))

    assert seen == {
        "app_user_id": "new-app",
        "manual_bearer_token": "",
        "user_id": "",
        "nick_name": "",
        "autonomy_id": "",
    }


def test_prompt_bind_setup_uses_input_order(monkeypatch):
    module = load_module()
    answers = iter(["新地址", "proof.jpg", "morning.jpg", "evening.jpg"])
    prompts = []
    monkeypatch.setattr("builtins.input", lambda prompt="": prompts.append(prompt) or next(answers))
    monkeypatch.setattr(
        module,
        "prepare_bind_setup_updates",
        lambda account_config, address, default_image, morning_image, evening_image: {
            "clock_address": address,
            "lng": 1.0,
            "lat": 2.0,
            "proof_image_path": default_image,
            "proof_images": {"morning": morning_image, "evening": evening_image},
        },
    )

    updates = module.prompt_bind_setup({"proof_images": {}})

    assert updates["clock_address"] == "新地址"
    assert updates["proof_images"]["morning"] == "morning.jpg"
    assert len(prompts) == 4


def test_interactive_auth_login_falls_back_to_selenium(monkeypatch):
    module = load_module()
    monkeypatch.setattr(
        module,
        "interactive_auth_login_via_playwright",
        lambda timeout_seconds=300: (_ for _ in ()).throw(module.CheckinError("pw failed")),
    )
    monkeypatch.setattr(
        module,
        "interactive_auth_login_via_selenium",
        lambda timeout_seconds=300: {"auth_token": "SELENIUM"},
    )

    result = module.interactive_auth_login(timeout_seconds=5)

    assert result["auth_token"] == "SELENIUM"


def test_ensure_account_session_uses_existing_token_without_rebind(monkeypatch):
    module = load_module()
    raw_config = {"manual_bearer_token": "OLD", "clock_address": "地址", "proof_image_path": "p.jpg"}
    monkeypatch.setattr(module, "get_bearer_token", lambda config, session: "TOKEN")
    monkeypatch.setattr(
        module,
        "bind_account",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should not bind")),
    )

    account_config, token = module.ensure_account_session(raw_config, config_path=Path("E:/c.json"))

    assert token == "TOKEN"
    assert account_config["manual_bearer_token"] == "OLD"


def test_ensure_account_session_saves_runtime_identity_updates(monkeypatch):
    module = load_module()
    raw_config = {"manual_bearer_token": "OLD", "autonomy_id": "old-plan"}
    saved = []

    def fake_get_bearer_token(config, session):
        config["autonomy_id"] = "new-plan"
        config["user_id"] = "new-user"
        return "TOKEN"

    monkeypatch.setattr(module, "get_bearer_token", fake_get_bearer_token)
    monkeypatch.setattr(module, "save_config", lambda config, config_path: saved.append((config_path, config.copy())))

    account_config, token = module.ensure_account_session(raw_config, config_path=Path("E:/c.json"))

    assert token == "TOKEN"
    assert account_config["autonomy_id"] == "new-plan"
    assert saved == [(Path("E:/c.json"), {"manual_bearer_token": "OLD", "autonomy_id": "new-plan", "user_id": "new-user"})]


def test_ensure_account_session_rebinds_when_token_invalid(monkeypatch):
    module = load_module()
    raw_config = {"accounts": [{"name": "default", "clock_address": "旧地址", "proof_image_path": "old.jpg"}]}
    calls = []

    def fake_get_bearer_token(config, session):
        calls.append(("get", config.get("app_user_id", "")))
        if len(calls) == 1:
            raise module.CheckinError("token expired")
        return "NEW_TOKEN"

    monkeypatch.setattr(module, "get_bearer_token", fake_get_bearer_token)

    def fake_bind_account(raw_config, *, config_path, account_name=None, timeout_seconds=300):
        calls.append(("bind", account_name))
        raw_config["accounts"][0]["app_user_id"] = "1500"
        raw_config["accounts"][0]["clock_address"] = "新地址"
        return {"app_user_id": "1500", "bearer_token": "IGNORED"}

    monkeypatch.setattr(module, "bind_account", fake_bind_account)

    account_config, token = module.ensure_account_session(raw_config, config_path=Path("E:/c.json"))

    assert token == "NEW_TOKEN"
    assert calls == [("get", ""), ("bind", None), ("get", "1500")]
    assert account_config["clock_address"] == "新地址"


def test_run_checkin_refreshes_token_and_retries_upload_on_401(monkeypatch):
    module = load_module()
    upload_tokens = []
    submit_tokens = []

    monkeypatch.setattr(
        module,
        "find_slot",
        lambda config, slot_name, now: {"name": "evening", "label": "晚上签到", "start_hour": 12, "end_hour": 24},
    )
    monkeypatch.setattr(module, "get_daily_clocks", lambda config, bearer_token, query_date, session: [])

    def fake_upload_image(config, bearer_token, session, slot):
        upload_tokens.append(bearer_token)
        if len(upload_tokens) == 1:
            raise module.CheckinError("上传图片失败: {'msg': '登录信息已过期,请重新登录', 'code': 401}")
        return "/file6/upload/a.jpg"

    monkeypatch.setattr(module, "upload_image", fake_upload_image)
    monkeypatch.setattr(module, "wait_for_uploaded_image", lambda config, remark, session: True)

    def fake_submit_checkin(config, bearer_token, remark, session, now):
        submit_tokens.append(bearer_token)
        return True

    monkeypatch.setattr(module, "submit_checkin", fake_submit_checkin)

    refreshed = []

    def fake_fetch_sxsx_bearer_token(config, session):
        refreshed.append(config.get("app_user_id"))
        return "NEW_TOKEN"

    monkeypatch.setattr(module, "fetch_sxsx_bearer_token", fake_fetch_sxsx_bearer_token)

    ok = module.run_checkin(
        config={
            "name": "default",
            "app_user_id": "1500",
            "upload_image": True,
            "verify_uploaded_image": True,
            "skip_if_already_signed": True,
        },
        bearer_token="OLD_TOKEN",
    )

    assert ok is True
    assert upload_tokens == ["OLD_TOKEN", "NEW_TOKEN"]
    assert submit_tokens == ["NEW_TOKEN"]
    assert refreshed == ["1500"]


def test_practice_plan_daily_query_uses_practice_clock_endpoint(monkeypatch):
    module = load_module()
    calls = []

    class Session:
        def request(self, method, url, **kwargs):
            calls.append((method, url, kwargs.get("params")))

            class Response:
                def raise_for_status(self):
                    return None

                def json(self):
                    return {"code": 200, "rows": []}

            return Response()

    rows = module.get_daily_clocks(
        {
            "sxsx_base_url": "https://example.test",
            "request_timeout": 30,
            "plan_type": "practicePlan",
            "practice_plan_id": "plan-1",
            "user_id": "user-1",
        },
        "TOKEN",
        datetime(2026, 4, 23).date(),
        Session(),
    )

    assert rows == []
    assert calls == [
        (
            "GET",
            "https://example.test/portal-api/practiceClock/practiceClock/getStuDailyClock",
            {
                "planId": "plan-1",
                "userId": "user-1",
                "queryDate": "2026-04-23",
                "beginQueryDate": "",
                "endQueryDate": "",
            },
        )
    ]


def test_practice_plan_submit_uses_plan_id_and_file_id(monkeypatch):
    module = load_module()
    calls = []

    def fake_request_json(session, method, url, **kwargs):
        calls.append((method, url, kwargs.get("json")))
        return {"code": 200}

    monkeypatch.setattr(module, "request_json", fake_request_json)

    ok = module.submit_checkin(
        {
            "sxsx_base_url": "https://example.test",
            "request_timeout": 30,
            "plan_type": "practicePlan",
            "practice_plan_id": "plan-1",
            "user_id": "user-1",
            "user_name": "student-name",
            "nick_name": "学生",
            "clock_address": "地址",
            "clock_type": "签到",
            "clock_content": "",
        },
        "TOKEN",
        "file-1",
        object(),
        datetime(2026, 4, 23, 8, 5, 0),
    )

    assert ok is True
    assert calls == [
        (
            "POST",
            "https://example.test/portal-api/practiceClock/practiceClock/add",
            {
                "planId": "plan-1",
                "userId": "user-1",
                "userName": "student-name",
                "nickName": "学生",
                "clockAddress": "地址",
                "fileId": "file-1",
                "clockTime": "2026-04-23 08:05:00",
                "clockType": "签到",
                "clockContent": "",
            },
        )
    ]


def test_practice_plan_run_checkin_skips_uploaded_image_url_verification(monkeypatch):
    module = load_module()
    submitted = []

    monkeypatch.setattr(
        module,
        "find_slot",
        lambda config, slot_name, now: {"name": "morning", "label": "早上签到", "start_hour": 0, "end_hour": 12},
    )
    monkeypatch.setattr(module, "get_daily_clocks", lambda config, bearer_token, query_date, session: [])
    monkeypatch.setattr(module, "upload_image", lambda config, bearer_token, session, slot: "file-id-1")

    def fail_wait_for_uploaded_image(config, remark, session):
        raise AssertionError("practicePlan uploads return fileId, not an image URL")

    monkeypatch.setattr(module, "wait_for_uploaded_image", fail_wait_for_uploaded_image)

    def fake_submit_checkin(config, bearer_token, remark, session, now):
        submitted.append(remark)
        return True

    monkeypatch.setattr(module, "submit_checkin", fake_submit_checkin)

    ok = module.run_checkin(
        config={
            "name": "default",
            "plan_type": "practicePlan",
            "practice_plan_id": "plan-1",
            "user_id": "user-1",
            "upload_image": True,
            "verify_uploaded_image": True,
            "skip_if_already_signed": True,
        },
        bearer_token="TOKEN",
    )

    assert ok is True
    assert submitted == ["file-id-1"]


def test_scheduler_evening_zero_records_runs_makeup_double_checkin(monkeypatch):
    module = load_module()
    calls = []
    sleeps = []

    account_config = {
        "name": "default",
        "slots": [
            {"name": "morning", "label": "早上签到", "start_hour": 0, "end_hour": 12},
            {"name": "evening", "label": "晚上签到", "start_hour": 12, "end_hour": 24},
        ],
    }

    monkeypatch.setattr(
        module,
        "find_slot",
        lambda config, slot_name, now: {"name": "evening", "label": "晚上签到", "start_hour": 12, "end_hour": 24},
    )
    monkeypatch.setattr(module, "ensure_account_session", lambda *args, **kwargs: (account_config, "TOKEN"))
    monkeypatch.setattr(module.requests, "Session", lambda: SimpleNamespace())
    monkeypatch.setattr(module, "get_daily_clocks", lambda config, bearer_token, query_date, session: [])
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    def fake_run_checkin(**kwargs):
        calls.append((kwargs["slot_name"], kwargs["config"].get("_forced_image_slot")))
        return True

    monkeypatch.setattr(module, "run_checkin", fake_run_checkin)

    module.run_slot_with_jitter(
        account_config,
        "evening",
        raw_config={"accounts": [account_config]},
        bind_timeout=300,
    )

    assert calls == [("morning", "morning"), ("evening", "evening")]
    assert sleeps == [10]


def test_scheduler_evening_nonzero_records_keeps_single_evening_run(monkeypatch):
    module = load_module()
    calls = []
    sleeps = []

    account_config = {
        "name": "default",
        "slots": [
            {"name": "morning", "label": "早上签到", "start_hour": 0, "end_hour": 12},
            {"name": "evening", "label": "晚上签到", "start_hour": 12, "end_hour": 24},
        ],
    }

    monkeypatch.setattr(
        module,
        "find_slot",
        lambda config, slot_name, now: {"name": "evening", "label": "晚上签到", "start_hour": 12, "end_hour": 24},
    )
    monkeypatch.setattr(module, "ensure_account_session", lambda *args, **kwargs: (account_config, "TOKEN"))
    monkeypatch.setattr(module.requests, "Session", lambda: SimpleNamespace())
    monkeypatch.setattr(
        module,
        "get_daily_clocks",
        lambda config, bearer_token, query_date, session: [{"clockTime": "2026-04-23 08:00:00"}],
    )
    monkeypatch.setattr(module.time, "sleep", lambda seconds: sleeps.append(seconds))

    def fake_run_checkin(**kwargs):
        calls.append((kwargs["slot_name"], kwargs["config"].get("_forced_image_slot")))
        return True

    monkeypatch.setattr(module, "run_checkin", fake_run_checkin)

    module.run_slot_with_jitter(
        account_config,
        "evening",
        raw_config={"accounts": [account_config]},
        bind_timeout=300,
    )

    assert calls == [("evening", None)]
    assert sleeps == []


def test_main_routes_run_scheduled_slot_now(monkeypatch):
    module = load_module()
    calls = []

    monkeypatch.setattr(sys, "argv", ["auto_checkin.py", "--run-scheduled-slot-now", "evening"])
    monkeypatch.setattr(module, "configure_logging", lambda verbose: None)
    monkeypatch.setattr(module, "load_config", lambda config_path=None: {"accounts": [{"name": "default"}]})
    monkeypatch.setattr(module, "iter_account_configs", lambda config, account_name=None: [{"name": "default"}])
    monkeypatch.setattr(
        module,
        "run_slot_now",
        lambda config, slot_name, **kwargs: calls.append((config.get("name"), slot_name, kwargs.get("raw_config"))),
    )

    assert module.main() == 0
    assert calls == [("default", "evening", {"accounts": [{"name": "default"}]})]


def test_prepare_upload_file_supports_remote_url(monkeypatch):
    module = load_module()

    class Response:
        status_code = 200
        content = b"img-bytes"
        headers = {"content-type": "image/png"}

        def raise_for_status(self):
            return None

    class Session:
        def get(self, url, **kwargs):
            return Response()

    monkeypatch.setattr(module, "requests", SimpleNamespace(RequestException=Exception))
    file_name, file_bytes, mime_type = module.prepare_upload_file("https://example.com/a.png", Session(), 10)

    assert file_name == "a.png"
    assert file_bytes == b"img-bytes"
    assert mime_type == "image/png"


def test_persist_bearer_token_updates_runtime_cache_and_script(monkeypatch):
    module = load_module()
    saved = []
    written = []
    monkeypatch.setattr(module, "save_token_cache", lambda payload, token_file: saved.append((payload, token_file)))
    monkeypatch.setattr(module, "update_script_manual_token", lambda token: written.append(token))
    monkeypatch.setattr(module, "token_file_for_account", lambda config: Path("E:/token.json"))
    config = {"name": "default", "manual_bearer_token": ""}

    module.persist_bearer_token(config, "NEW_TOKEN")

    assert config["manual_bearer_token"] == "NEW_TOKEN"
    assert saved[0][0]["sxsx_bearer_token"] == "NEW_TOKEN"
    assert written == ["NEW_TOKEN"]
