#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
江西职教实习平台自动签到脚本。

默认每天 08:05 和 19:05 各签到一次。每次运行会：
1. 通过 appUserId 换取实习平台 Bearer JWT。
2. 查询当天签到记录，避免同一时段重复签到。
3. 上传 proof.jpg，并解密上传接口返回的图片路径。
4. 提交自主实习签到。
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import mimetypes
import random
import re
import sys
import time
import urllib.parse
from copy import deepcopy
from datetime import date, datetime
from pathlib import Path
from typing import Any

import requests


SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CONFIG_FILE = SCRIPT_DIR / "checkin_config.json"
DEFAULT_TOKEN_FILE = SCRIPT_DIR / "token.json"
DEFAULT_LOG_FILE = SCRIPT_DIR / "checkin.log"

SXSX_AES_KEY = b"qscvjsuqiqksoq10"
SXSX_SM2_PUBLIC_KEY = (
    "04d92469937d4af9b055d33175dd167e533c166b7b90e3a387a1e657bde6d18b"
    "e76b324487c4fe6dc9e881930dbe8dcaae8af38c5aa18d2f0bb9cd2883fb075628"
)
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 9; NX789S Build/PQ3B.190801.04221524; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/91.0.4472.114 Safari/537.36 uni-app Html5Plus/1.0 (Immersed/24.0)"
)

# =========================
# 入口全局配置
# 直接改这里即可，不改 JSON 也能用。
# 图片既支持本地路径，也支持 http/https 图片地址。
# 经纬度使用 GCJ-02。
# =========================

# 平台基础地址
SXSX_BASE_URL = "https://sxsx.jxeduyun.com:7780"

MANUAL_BEARER_TOKEN = ""
# 如果你不想填账号密码，也可以只填它，脚本会用它去换 token。
APP_USER_ID = ""

# 账号密码直登。
# 建议优先填这个，脚本会直接调用 /portal-api/app/index/login 获取 token。
LOGIN_ACCOUNT = ""
LOGIN_PASSWORD = ""
LOGIN_USER_TYPE = "student"
ENROLLMENT_YEAR = ""

# 下面三个值会在登录成功后尽量自动补全。
# 如果你已经知道，直接填上会更稳。
# AUTONOMY_ID = "525676526a3a13ad106551a8994d6fbe"
# USER_ID = "d2f07a6eb4c54839ba3e696837fcb588"
# NICK_NAME = "邱日东"
AUTONOMY_ID = ""
USER_ID = ""
NICK_NAME = ""

# 默认签到地址。
# 这里已经按你最开始发包里的地址预填。
CLOCK_ADDRESS = ""

# 签到经纬度，GCJ-02
LNG = 0.0
LAT = 0.0

# 图片配置。
# 支持本地文件路径，也支持网络图片 URL。
PROOF_IMAGE_PATH = "proof.jpg"
PROOF_IMAGES = {
    "morning": "proof_morning.jpg",
    "evening": "proof_evening.jpg",
}

# 是否上传图片。
UPLOAD_IMAGE = True

# 上传后是否轮询图片 URL，确认服务器侧能访问到了再提交签到。
VERIFY_UPLOADED_IMAGE = True
VERIFY_UPLOADED_IMAGE_TIMEOUT = 60
VERIFY_UPLOADED_IMAGE_INTERVAL = 2

# 签到表单附加字段
CLOCK_TYPE = "签到"
CLOCK_CONTENT = ""

# 是否检测当前时段已签到并跳过
SKIP_IF_ALREADY_SIGNED = True

# 请求超时时间，单位秒
REQUEST_TIMEOUT = 30

# 定时时段配置
SLOTS = [
    {
        "name": "morning",
        "label": "早上签到",
        "time": "08:05",
        "start_hour": 0,
        "end_hour": 12,
        "jitter_minutes": 5,
    },
    {
        "name": "evening",
        "label": "晚上签到",
        "time": "19:05",
        "start_hour": 12,
        "end_hour": 24,
        "jitter_minutes": 5,
    },
]


def build_global_config() -> dict[str, Any]:
    return {
        "name": "default",
        "sxsx_base_url": SXSX_BASE_URL,
        "manual_bearer_token": MANUAL_BEARER_TOKEN,
        "app_user_id": APP_USER_ID,
        "login_account": LOGIN_ACCOUNT,
        "login_password": LOGIN_PASSWORD,
        "login_user_type": LOGIN_USER_TYPE,
        "enrollment_year": ENROLLMENT_YEAR,
        "autonomy_id": AUTONOMY_ID,
        "user_id": USER_ID,
        "nick_name": NICK_NAME,
        "clock_address": CLOCK_ADDRESS,
        "lng": LNG,
        "lat": LAT,
        "proof_image_path": PROOF_IMAGE_PATH,
        "proof_images": deepcopy(PROOF_IMAGES),
        "upload_image": UPLOAD_IMAGE,
        "verify_uploaded_image": VERIFY_UPLOADED_IMAGE,
        "verify_uploaded_image_timeout": VERIFY_UPLOADED_IMAGE_TIMEOUT,
        "verify_uploaded_image_interval": VERIFY_UPLOADED_IMAGE_INTERVAL,
        "clock_type": CLOCK_TYPE,
        "clock_content": CLOCK_CONTENT,
        "skip_if_already_signed": SKIP_IF_ALREADY_SIGNED,
        "request_timeout": REQUEST_TIMEOUT,
        "accounts": [],
        "slots": deepcopy(SLOTS),
    }


DEFAULT_CONFIG = build_global_config()


class CheckinError(RuntimeError):
    """Raised when a check-in step fails."""


def configure_logging(verbose: bool = False) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(DEFAULT_LOG_FILE, encoding="utf-8"),
    ]
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
        force=True,
    )


def deep_merge(defaults: dict[str, Any], overrides: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(defaults)
    for key, value in overrides.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def load_config(config_path: Path = DEFAULT_CONFIG_FILE) -> dict[str, Any]:
    if not config_path.exists():
        return deepcopy(DEFAULT_CONFIG)
    with config_path.open("r", encoding="utf-8") as f:
        return deep_merge(DEFAULT_CONFIG, json.load(f))


def init_config(config_path: Path = DEFAULT_CONFIG_FILE) -> None:
    if config_path.exists():
        logging.info("配置文件已存在: %s", config_path)
        return
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(DEFAULT_CONFIG, f, ensure_ascii=False, indent=2)
    logging.info("已生成配置文件: %s", config_path)


def load_token_cache(token_file: Path = DEFAULT_TOKEN_FILE) -> dict[str, Any]:
    if not token_file.exists():
        return {}
    with token_file.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_token_cache(tokens: dict[str, Any], token_file: Path = DEFAULT_TOKEN_FILE) -> None:
    with token_file.open("w", encoding="utf-8") as f:
        json.dump(tokens, f, ensure_ascii=False, indent=2)


def update_script_manual_token(token: str, script_path: Path = Path(__file__).resolve()) -> None:
    try:
        original = script_path.read_text(encoding="utf-8")
        updated = re.sub(
            r'^MANUAL_BEARER_TOKEN = ".*"$',
            f'MANUAL_BEARER_TOKEN = {json.dumps(token, ensure_ascii=False)}',
            original,
            count=1,
            flags=re.MULTILINE,
        )
        if updated != original:
            script_path.write_text(updated, encoding="utf-8")
    except OSError:
        logging.warning("回写脚本中的 MANUAL_BEARER_TOKEN 失败", exc_info=True)


def persist_bearer_token(config: dict[str, Any], token: str) -> None:
    config["manual_bearer_token"] = token
    save_token_cache(
        {"sxsx_bearer_token": token, "updated_at": datetime.now().isoformat(timespec="seconds")},
        token_file_for_account(config),
    )
    update_script_manual_token(token)


def resolve_local_path(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return SCRIPT_DIR / path


def slugify_account_name(name: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9_.-]+", "-", name.strip()).strip(".-")
    return slug or "default"


def token_file_for_account(config: dict[str, Any]) -> Path:
    if config.get("token_file"):
        return resolve_local_path(str(config["token_file"]))
    name = slugify_account_name(str(config.get("name", "default")))
    if name == "default":
        return DEFAULT_TOKEN_FILE
    return SCRIPT_DIR / f"token.{name}.json"


def has_direct_login_credentials(config: dict[str, Any]) -> bool:
    return bool(config.get("login_account") and config.get("login_password"))


def iter_account_configs(config: dict[str, Any], selected_account: str | None = None):
    base = {key: value for key, value in config.items() if key != "accounts"}
    accounts = config.get("accounts") or [{"name": "default"}]
    for account in accounts:
        merged = deep_merge(base, account)
        merged.setdefault("name", account.get("name", "default"))
        if selected_account and merged["name"] != selected_account:
            continue
        yield merged


def decrypt_sxsx_data(encrypted_text: str) -> Any:
    from cryptography.hazmat.primitives import padding
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

    encrypted_bytes = base64.b64decode(encrypted_text)
    decryptor = Cipher(algorithms.AES(SXSX_AES_KEY), modes.ECB()).decryptor()
    padded = decryptor.update(encrypted_bytes) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    raw = unpadder.update(padded) + unpadder.finalize()
    text = raw.decode("utf-8").replace("\x00", "")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def encrypt_password_sm2(password: str) -> str:
    from gmssl import sm2

    crypt = sm2.CryptSM2(private_key="", public_key=SXSX_SM2_PUBLIC_KEY, mode=1)
    encrypted = crypt.encrypt(password.encode("utf-8")).hex()
    return "04" + encrypted


def build_portal_login_payload(config: dict[str, Any]) -> dict[str, Any]:
    encrypted_password = encrypt_password_sm2(str(config["login_password"]))
    return {
        "appLogin": True,
        "loginAccount": str(config["login_account"]).strip(),
        "password": urllib.parse.quote(encrypted_password, safe=""),
        "appUserId": str(config.get("app_user_id", "")),
        "loginUserType": config.get("login_user_type", "student"),
        "enrollmentYear": str(config.get("enrollment_year", "")),
    }


def decode_sxsx_response(payload: dict[str, Any]) -> dict[str, Any]:
    decoded = deepcopy(payload)
    if decoded.get("code") == 200 and decoded.get("needDe"):
        if decoded.get("rowsEn"):
            decoded["rows"] = decrypt_sxsx_data(decoded["rowsEn"])
            decoded["needDe"] = False
        elif decoded.get("data") is not None:
            decoded["data"] = decrypt_sxsx_data(decoded["data"])
            decoded["needDe"] = False
    return decoded


def extract_upload_remark(payload: dict[str, Any]) -> str:
    decoded = decode_sxsx_response(payload)
    if decoded.get("code") != 200:
        raise CheckinError(f"上传图片失败: {decoded}")

    data = decoded.get("data")
    if isinstance(data, str):
        return data
    if isinstance(data, dict):
        for key in ("remark", "url", "filePath"):
            value = data.get(key)
            if value:
                return str(value)
        nested = data.get("data")
        if isinstance(nested, dict):
            for key in ("remark", "url", "filePath"):
                value = nested.get(key)
                if value:
                    return str(value)

    raise CheckinError(f"上传成功但未找到图片路径: {decoded}")


def build_headers(bearer_token: str | None = None, *, content_type: str | None = "application/json;charset=utf-8") -> dict[str, str]:
    headers = {
        "accept": "application/json, text/javascript, */*; q=0.01",
        "user-agent": USER_AGENT,
        "x-requested-with": "com.ecom.renrentong",
        "accept-language": "zh-CN,zh;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    if content_type:
        headers["content-type"] = content_type
    if bearer_token:
        headers["authorization"] = f"Bearer {bearer_token}"
    return headers


def request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    timeout: int,
    **kwargs: Any,
) -> dict[str, Any]:
    response = session.request(method, url, timeout=timeout, **kwargs)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise CheckinError(f"接口返回不是 JSON 对象: {url}")
    return decode_sxsx_response(payload)


def fetch_user_info(config: dict[str, Any], bearer_token: str, session: requests.Session) -> dict[str, Any]:
    url = f"{config['sxsx_base_url']}/portal-api/app/index/getUserInfo"
    payload = request_json(
        session,
        "GET",
        url,
        headers=build_headers(bearer_token),
        timeout=int(config["request_timeout"]),
    )
    return payload.get("data") or {}


def fetch_student_plan(config: dict[str, Any], bearer_token: str, session: requests.Session) -> dict[str, Any]:
    url = f"{config['sxsx_base_url']}/portal-api/app/index/getStudentPlan"
    payload = request_json(
        session,
        "GET",
        url,
        headers=build_headers(bearer_token),
        timeout=int(config["request_timeout"]),
    )
    return payload.get("data") or {}


def populate_runtime_config(config: dict[str, Any], bearer_token: str, session: requests.Session, user_info: dict[str, Any] | None = None) -> None:
    user_info = user_info or fetch_user_info(config, bearer_token, session)
    if user_info:
        config["user_id"] = user_info.get("userId") or config.get("user_id", "")
        config["nick_name"] = user_info.get("nickName") or config.get("nick_name", "")

    if not config.get("autonomy_id"):
        plan_data = fetch_student_plan(config, bearer_token, session)
        autonomy_plan = plan_data.get("autonomyPlan")
        if autonomy_plan and autonomy_plan.get("id"):
            config["autonomy_id"] = autonomy_plan["id"]
        else:
            raise CheckinError("当前账号未查询到自主实习 autonomy_id，请手动在配置中填写")


def login_and_fetch_runtime_context(config: dict[str, Any], session: requests.Session) -> dict[str, Any]:
    payload = build_portal_login_payload(config)
    url = f"{config['sxsx_base_url']}/portal-api/app/index/login"
    response = request_json(
        session,
        "POST",
        url,
        json=payload,
        headers=build_headers(content_type="application/json;charset=utf-8"),
        timeout=int(config["request_timeout"]),
    )
    data = response.get("data") or {}
    token = data.get("token")
    if not token:
        raise CheckinError(f"账号密码登录失败: {response}")

    config["user_id"] = data.get("userId") or config.get("user_id", "")
    config["nick_name"] = data.get("nickName") or config.get("nick_name", "")
    populate_runtime_config(config, token, session, user_info=data)
    persist_bearer_token(config, token)
    return {"token": token, "user_info": data}


def fetch_sxsx_bearer_token(config: dict[str, Any], session: requests.Session | None = None) -> str:
    session = session or requests.Session()
    if not config.get("app_user_id"):
        raise CheckinError(
            "缺少 app_user_id。账号密码登录会触发点选验证码，脚本不会绕过验证码；"
            "请先手动登录一次并把该账号的 app_user_id 填入配置。"
        )
    url = f"{config['sxsx_base_url']}/portal-api/app/index/checkAppUserIdNew"
    payload = request_json(
        session,
        "GET",
        url,
        params={"appUserId": config["app_user_id"]},
        headers=build_headers(content_type="application/json;charset=utf-8"),
        timeout=int(config["request_timeout"]),
    )
    token = payload.get("data", {}).get("userInfo", {}).get("token")
    user_info = payload.get("data", {}).get("userInfo") or {}
    if not token:
        raise CheckinError(f"未能从 checkAppUserIdNew 获取签到 Token: {payload}")
    if user_info:
        config["user_id"] = user_info.get("userId") or config.get("user_id", "")
        config["nick_name"] = user_info.get("nickName") or config.get("nick_name", "")
    populate_runtime_config(config, token, session, user_info=user_info)
    persist_bearer_token(config, token)
    return token


def get_bearer_token(config: dict[str, Any], session: requests.Session) -> str:
    config = deep_merge(DEFAULT_CONFIG, config)
    errors: list[str] = []
    token_file = token_file_for_account(config)
    cached = load_token_cache(token_file).get("sxsx_bearer_token")
    manual = config.get("manual_bearer_token")

    for source_name, token in (
        ("缓存 token", cached),
        ("手动 token", manual),
    ):
        if not token:
            continue
        try:
            populate_runtime_config(config, str(token), session)
            logging.info("%s 有效，优先使用", source_name)
            return str(token)
        except Exception as exc:
            errors.append(f"{source_name}不可用: {exc}")
            logging.warning("%s 不可用，继续尝试其他方式", source_name)

    if has_direct_login_credentials(config):
        try:
            token = str(login_and_fetch_runtime_context(config, session)["token"])
            logging.info("账号密码直登获取新 token 成功")
            return token
        except Exception as exc:
            errors.append(f"账号密码直登失败: {exc}")

    if config.get("app_user_id"):
        try:
            token = fetch_sxsx_bearer_token(config, session)
            logging.info("app_user_id 换取新 token 成功")
            return token
        except Exception as exc:
            errors.append(f"app_user_id 换 token 失败: {exc}")

    raise CheckinError("；".join(errors) or "没有可用的 token 获取方式")


def get_daily_clocks(
    config: dict[str, Any],
    bearer_token: str,
    query_date: date,
    session: requests.Session,
) -> list[dict[str, Any]]:
    url = f"{config['sxsx_base_url']}/portal-api/practice/autonomyClock/getStuDailyClock"
    payload = request_json(
        session,
        "GET",
        url,
        params={
            "autonomyId": config["autonomy_id"],
            "userId": config["user_id"],
            "queryDate": query_date.strftime("%Y-%m-%d"),
            "beginQueryDate": "",
            "endQueryDate": "",
        },
        headers=build_headers(bearer_token),
        timeout=int(config["request_timeout"]),
    )
    rows = payload.get("rows") or []
    if not isinstance(rows, list):
        raise CheckinError(f"签到记录格式异常: {payload}")
    return rows


def parse_clock_time(value: str) -> datetime | None:
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def has_clock_in_slot(clocks: list[dict[str, Any]], slot: dict[str, Any]) -> bool:
    start_hour = int(slot["start_hour"])
    end_hour = int(slot["end_hour"])
    for clock in clocks:
        clock_time = parse_clock_time(str(clock.get("clockTime", "")))
        if clock_time and start_hour <= clock_time.hour < end_hour:
            return True
    return False


def pick_slot(now: datetime, slots: list[dict[str, Any]]) -> dict[str, Any]:
    for slot in slots:
        if int(slot["start_hour"]) <= now.hour < int(slot["end_hour"]):
            return slot
    return slots[0]


def find_slot(config: dict[str, Any], slot_name: str | None, now: datetime) -> dict[str, Any]:
    slots = config["slots"]
    if slot_name:
        for slot in slots:
            if slot["name"] == slot_name:
                return slot
        raise CheckinError(f"未知签到时段: {slot_name}")
    return pick_slot(now, slots)


def uploaded_image_url(config: dict[str, Any], remark: str) -> str:
    if remark.startswith("http://") or remark.startswith("https://"):
        return remark
    if not remark.startswith("/"):
        remark = f"/{remark}"
    return f"{config['sxsx_base_url']}{remark}"


def image_path_for_slot(config: dict[str, Any], slot: dict[str, Any]) -> Path:
    proof_images = config.get("proof_images") or {}
    slot_path = proof_images.get(slot.get("name"))
    return resolve_local_path(slot_path or config["proof_image_path"])


def prepare_upload_file(path_value: str, session: requests.Session, timeout: int) -> tuple[str, bytes, str]:
    if path_value.startswith("http://") or path_value.startswith("https://"):
        response = session.get(path_value, timeout=timeout)
        response.raise_for_status()
        mime_type = response.headers.get("content-type", "").split(";")[0].strip() or "image/jpeg"
        file_name = Path(urllib.parse.urlparse(path_value).path).name or "upload-image"
        return file_name, response.content, mime_type

    image_path = resolve_local_path(path_value)
    if not image_path.exists():
        raise CheckinError(f"签到证明图片不存在: {image_path}")
    mime_type = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"
    return image_path.name, image_path.read_bytes(), mime_type


def wait_for_uploaded_image(config: dict[str, Any], remark: str, session: requests.Session) -> bool:
    timeout = float(config.get("verify_uploaded_image_timeout", 60))
    interval = float(config.get("verify_uploaded_image_interval", 2))
    deadline = time.monotonic() + timeout
    url = uploaded_image_url(config, remark)

    while True:
        try:
            response = session.get(
                url,
                headers={
                    "user-agent": USER_AGENT,
                    "accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
                    "x-requested-with": "com.ecom.renrentong",
                },
                timeout=int(config.get("request_timeout", 30)),
                stream=True,
            )
            try:
                content_type = response.headers.get("content-type", "")
                if response.status_code == 200 and content_type.lower().startswith("image/"):
                    return True
            finally:
                response.close()
        except requests.RequestException:
            logging.debug("图片暂不可访问，继续等待: %s", url, exc_info=True)

        if time.monotonic() >= deadline:
            return False
        time.sleep(interval)


def upload_image(config: dict[str, Any], bearer_token: str, session: requests.Session, slot: dict[str, Any]) -> str:
    image_source = str((config.get("proof_images") or {}).get(slot.get("name")) or config["proof_image_path"])
    url = f"{config['sxsx_base_url']}/portal-api/practiceClock/practiceClock/uploadClockFile"
    file_name, file_bytes, mime_type = prepare_upload_file(image_source, session, int(config["request_timeout"]))
    response = session.post(
        url,
        headers=build_headers(bearer_token, content_type=None),
        files={"file": (file_name, file_bytes, mime_type)},
        timeout=int(config["request_timeout"]),
    )
    response.raise_for_status()
    return extract_upload_remark(response.json())


def submit_checkin(
    config: dict[str, Any],
    bearer_token: str,
    remark: str,
    session: requests.Session,
    now: datetime,
) -> bool:
    url = f"{config['sxsx_base_url']}/portal-api/practice/autonomyClock/add"
    payload = {
        "autonomyId": config["autonomy_id"],
        "userId": config["user_id"],
        "nickName": config["nick_name"],
        "clockAddress": config["clock_address"],
        "fileId": "",
        "clockTime": now.strftime("%Y-%m-%d %H:%M:%S"),
        "clockType": config["clock_type"],
        "clockContent": config.get("clock_content", ""),
        "lng": config["lng"],
        "lat": config["lat"],
        "remark": remark,
    }
    decoded = request_json(
        session,
        "POST",
        url,
        json=payload,
        headers=build_headers(bearer_token),
        timeout=int(config["request_timeout"]),
    )
    return decoded.get("code") == 200


def run_checkin(
    *,
    config: dict[str, Any] | None = None,
    slot_name: str | None = None,
    dry_run: bool = False,
    force: bool = False,
) -> bool:
    config = config or load_config()
    now = datetime.now()
    slot = find_slot(config, slot_name, now)
    session = requests.Session()

    logging.info("开始%s: %s", slot.get("label", slot["name"]), now.strftime("%Y-%m-%d %H:%M:%S"))
    logging.info("账户: %s", config.get("name", "default"))
    bearer_token = get_bearer_token(config, session)
    clocks = get_daily_clocks(config, bearer_token, now.date(), session)
    logging.info("今日已有签到记录 %s 条", len(clocks))

    if config.get("skip_if_already_signed", True) and not force and has_clock_in_slot(clocks, slot):
        logging.info("当前时段已经签到，跳过提交")
        return True

    if dry_run:
        logging.info("dry-run 模式：已完成 Token 和记录查询，不上传、不提交")
        return True

    remark = ""
    if config.get("upload_image", True):
        remark = upload_image(config, bearer_token, session, slot)
        logging.info("图片上传成功: %s", remark)
        if config.get("verify_uploaded_image", True):
            if not wait_for_uploaded_image(config, remark, session):
                raise CheckinError(f"图片上传后未能在限定时间内访问: {uploaded_image_url(config, remark)}")
            logging.info("图片已确认可访问")

    if submit_checkin(config, bearer_token, remark, session, now):
        logging.info("签到成功")
        return True

    raise CheckinError("签到接口未返回成功")


def run_slot_with_jitter(config: dict[str, Any], slot_name: str) -> None:
    slot = find_slot(config, slot_name, datetime.now())
    jitter_seconds = max(0, int(slot.get("jitter_minutes", 0))) * 60
    if jitter_seconds:
        delay = random.randint(0, jitter_seconds)
        logging.info("%s 随机延迟 %s 秒后执行", slot.get("label", slot_name), delay)
        time.sleep(delay)
    try:
        run_checkin(config=config, slot_name=slot_name)
    except Exception:
        logging.exception("%s 执行失败", slot.get("label", slot_name))


def run_scheduler(config: dict[str, Any]) -> None:
    try:
        import schedule
    except ModuleNotFoundError as exc:
        raise CheckinError("缺少依赖 schedule，请先执行: pip install schedule") from exc

    scheduled = 0
    for account_config in iter_account_configs(config):
        for slot in account_config["slots"]:
            schedule.every().day.at(slot["time"]).do(run_slot_with_jitter, account_config, slot["name"])
            logging.info(
                "已安排账户 %s 的 %s: 每天 %s",
                account_config.get("name", "default"),
                slot.get("label", slot["name"]),
                slot["time"],
            )
            scheduled += 1
    if scheduled == 0:
        raise CheckinError("没有可调度的账户")

    while True:
        schedule.run_pending()
        time.sleep(30)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="江西职教实习平台自动签到")
    parser.add_argument("--config", default=str(DEFAULT_CONFIG_FILE), help="配置文件路径")
    parser.add_argument("--init-config", action="store_true", help="生成默认配置文件后退出")
    parser.add_argument("--once", action="store_true", help="立即执行一次签到")
    parser.add_argument("--account", help="只执行指定账户 name")
    parser.add_argument("--slot", choices=["morning", "evening"], help="指定签到时段")
    parser.add_argument("--dry-run", action="store_true", help="只验证 Token 和查询记录，不提交")
    parser.add_argument("--force", action="store_true", help="忽略重复签到检查，强制提交")
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    configure_logging(args.verbose)

    config_path = Path(args.config)
    if args.init_config:
        init_config(config_path)
        return 0

    config = load_config(config_path)
    try:
        if args.once or args.dry_run:
            account_configs = list(iter_account_configs(config, args.account))
            if not account_configs:
                raise CheckinError(f"未找到账户: {args.account}")
            ok = True
            for account_config in account_configs:
                ok = run_checkin(
                    config=account_config,
                    slot_name=args.slot,
                    dry_run=args.dry_run,
                    force=args.force,
                ) and ok
            return 0 if ok else 1
        run_scheduler(config)
        return 0
    except Exception:
        logging.exception("自动签到失败")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
