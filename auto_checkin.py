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
import math
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
from uuid import uuid4

import requests


def get_script_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


SCRIPT_DIR = get_script_dir()
DEFAULT_CONFIG_FILE = SCRIPT_DIR / "checkin_config.json"
DEFAULT_TOKEN_FILE = SCRIPT_DIR / "token.json"
DEFAULT_LOG_FILE = SCRIPT_DIR / "checkin.log"

SXSX_AES_KEY = b"qscvjsuqiqksoq10"
USER_AGENT = (
    "Mozilla/5.0 (Linux; Android 9; NX789S Build/PQ3B.190801.04221524; wv) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 "
    "Chrome/91.0.4472.114 Safari/537.36 uni-app Html5Plus/1.0 (Immersed/24.0)"
)
AUTH_BASE_URL = "https://auth.jx.smartedu.cn:8880"
AUTH_USER_AGENT = "okhttp/4.10.0"
BIND_GEOCODER_URL = "https://nominatim.openstreetmap.org/search"
EDGE_BINARY_PATH = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
CHROME_BINARY_PATH = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")

# =========================
# 入口全局配置
# 直接改这里即可，不改 JSON 也能用。
# 图片既支持本地路径，也支持 http/https 图片地址。
# 经纬度使用 GCJ-02。
# =========================

# 平台基础地址
SXSX_BASE_URL = "https://sxsx.jxeduyun.com:7780"

MANUAL_BEARER_TOKEN = ""
# 可以留空。脚本会优先复用缓存/手填 token，不可用时再走 app_user_id 换 token。
APP_USER_ID = ""

# 预留字段。旧的 /portal-api/app/index/login 已废弃，当前脚本不会再尝试它。
# 目前平台真实登录链路经过统一认证和点选验证码；脚本主链路仍是 app_user_id -> checkAppUserIdNew。
LOGIN_ACCOUNT = ""
LOGIN_PASSWORD = ""
LOGIN_USER_TYPE = "student"
ENROLLMENT_YEAR = ""

# 下面三个值会在登录成功后尽量自动补全。
# 如果你已经知道，直接填上会更稳。
AUTONOMY_ID = ""
USER_ID = ""
USER_NAME = ""
NICK_NAME = ""

# 默认签到地址。实际使用建议通过 --bind-account 写入 checkin_config.json。
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
        "user_name": USER_NAME,
        "nick_name": NICK_NAME,
        "plan_type": "",
        "practice_plan_id": "",
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


def save_config(config: dict[str, Any], config_path: Path = DEFAULT_CONFIG_FILE) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with config_path.open("w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def clear_account_identity_fields(config: dict[str, Any]) -> None:
    for key in ("manual_bearer_token", "user_id", "user_name", "nick_name", "autonomy_id", "plan_type", "practice_plan_id"):
        config[key] = ""


def load_token_cache(token_file: Path = DEFAULT_TOKEN_FILE) -> dict[str, Any]:
    if not token_file.exists():
        return {}
    with token_file.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_token_cache(tokens: dict[str, Any], token_file: Path = DEFAULT_TOKEN_FILE) -> None:
    with token_file.open("w", encoding="utf-8") as f:
        json.dump(tokens, f, ensure_ascii=False, indent=2)


def update_script_manual_token(token: str, script_path: Path = Path(__file__).resolve()) -> None:
    if getattr(sys, "frozen", False):
        return
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


def get_single_account_config(config: dict[str, Any], account_name: str | None = None) -> dict[str, Any]:
    account_configs = list(iter_account_configs(config, account_name))
    if not account_configs:
        raise CheckinError(f"未找到账户: {account_name}")
    if len(account_configs) > 1:
        raise CheckinError("存在多个账户，请使用 --account 指定要绑定的账户")
    return account_configs[0]


def apply_account_updates(
    config: dict[str, Any],
    updates: dict[str, Any],
    account_name: str | None = None,
    *,
    keep_empty: bool = False,
) -> None:
    cleaned = dict(updates) if keep_empty else {key: value for key, value in updates.items() if value not in (None, "")}
    accounts = config.get("accounts") or []

    if accounts:
        target_name = account_name
        if target_name is None:
            if len(accounts) > 1:
                raise CheckinError("存在多个账户，请使用 --account 指定要写回的账户")
            target_name = accounts[0].get("name", "default")
        for account in accounts:
            if account.get("name", "default") == target_name:
                account.update(cleaned)
                return
        raise CheckinError(f"未找到账户: {target_name}")

    config.update(cleaned)


def is_remote_resource(path_value: str) -> bool:
    return path_value.startswith("http://") or path_value.startswith("https://")


def validate_image_source(path_value: str) -> None:
    if not path_value:
        raise CheckinError("图片路径不能为空")
    if is_remote_resource(path_value):
        return
    image_path = resolve_local_path(path_value)
    if not image_path.exists():
        raise CheckinError(f"图片不存在: {image_path}")


def out_of_china(lng: float, lat: float) -> bool:
    return not (73.66 < lng < 135.05 and 3.86 < lat < 53.55)


def transform_lat(lng: float, lat: float) -> float:
    ret = (
        -100.0
        + 2.0 * lng
        + 3.0 * lat
        + 0.2 * lat * lat
        + 0.1 * lng * lat
        + 0.2 * math.sqrt(abs(lng))
    )
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * math.pi) + 40.0 * math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * math.pi) + 320 * math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
    return ret


def transform_lng(lng: float, lat: float) -> float:
    ret = (
        300.0
        + lng
        + 2.0 * lat
        + 0.1 * lng * lng
        + 0.1 * lng * lat
        + 0.1 * math.sqrt(abs(lng))
    )
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 * math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * math.pi) + 40.0 * math.sin(lng / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * math.pi) + 300.0 * math.sin(lng / 30.0 * math.pi)) * 2.0 / 3.0
    return ret


def wgs84_to_gcj02(lng: float, lat: float) -> tuple[float, float]:
    if out_of_china(lng, lat):
        return lng, lat
    a = 6378245.0
    ee = 0.00669342162296594323
    dlat = transform_lat(lng - 105.0, lat - 35.0)
    dlng = transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    return lng + dlng, lat + dlat


def query_geocoder_rows(address: str, session: requests.Session) -> list[dict[str, Any]]:
    response = session.get(
        BIND_GEOCODER_URL,
        params={"q": address, "format": "jsonv2", "limit": 1},
        headers={"user-agent": f"auto-checkin/1.0 ({AUTH_BASE_URL})"},
        timeout=30,
    )
    response.raise_for_status()
    rows = response.json()
    if not isinstance(rows, list):
        return []
    return rows


def extract_parent_region(address: str) -> str | None:
    stripped = address.strip()
    for marker in ("区", "县", "旗", "市"):
        idx = stripped.rfind(marker)
        if idx > 0:
            return stripped[: idx + 1]
    return None


def extract_state_name(display_name: str) -> str | None:
    for part in [item.strip() for item in display_name.split(",")]:
        if part.endswith(("省", "自治区", "特别行政区")):
            return part
    return None


def row_to_gcj02(row: dict[str, Any]) -> tuple[float, float]:
    lng = float(row["lon"])
    lat = float(row["lat"])
    return wgs84_to_gcj02(lng, lat)


def geocode_address_to_gcj02(address: str, session: requests.Session | None = None) -> tuple[float, float]:
    session = session or requests.Session()
    rows = query_geocoder_rows(address, session)
    if rows:
        return row_to_gcj02(rows[0])

    parent_region = extract_parent_region(address)
    parent_row: dict[str, Any] | None = None
    if parent_region and parent_region != address:
        parent_rows = query_geocoder_rows(parent_region, session)
        if parent_rows:
            parent_row = parent_rows[0]
            state_name = extract_state_name(str(parent_row.get("display_name", "")))
            if state_name:
                expanded_rows = query_geocoder_rows(f"{state_name}{address}", session)
                if expanded_rows:
                    logging.info("地址解析已自动补全省份: %s -> %s%s", address, state_name, address)
                    return row_to_gcj02(expanded_rows[0])

    if parent_row:
        logging.warning("地址未命中详细地点，已回退到父级区域坐标: %s", parent_region)
        return row_to_gcj02(parent_row)

    raise CheckinError(f"地址解析失败，请换一个更完整的地址: {address}")


def prepare_bind_setup_updates(
    account_config: dict[str, Any],
    *,
    address: str,
    default_image: str,
    morning_image: str,
    evening_image: str,
) -> dict[str, Any]:
    address = address.strip()
    default_image = default_image.strip()
    morning_image = morning_image.strip()
    evening_image = evening_image.strip()
    if not address:
        raise CheckinError("签到地址不能为空")
    validate_image_source(default_image)
    if morning_image:
        validate_image_source(morning_image)
    if evening_image:
        validate_image_source(evening_image)
    lng, lat = geocode_address_to_gcj02(address)
    proof_images: dict[str, str] = {}
    if morning_image:
        proof_images["morning"] = morning_image
    if evening_image:
        proof_images["evening"] = evening_image
    return {
        "clock_address": address,
        "lng": round(lng, 6),
        "lat": round(lat, 6),
        "proof_image_path": default_image,
        "proof_images": proof_images,
    }


def prompt_with_default(prompt: str, current: str, *, allow_clear: bool = False) -> str:
    suffix = f" [{current}]" if current else ""
    clear_hint = "，输入 - 清空" if allow_clear else ""
    value = input(f"{prompt}{suffix}{clear_hint}: ").strip()
    if allow_clear and value == "-":
        return ""
    return value or current


def prompt_bind_setup(account_config: dict[str, Any]) -> dict[str, Any]:
    current_images = account_config.get("proof_images") or {}
    address = prompt_with_default("请输入签到地址", str(account_config.get("clock_address", "")))
    default_image = prompt_with_default("请输入默认签到图片路径", str(account_config.get("proof_image_path", "")))
    morning_image = prompt_with_default(
        "请输入早上签到图片路径",
        str(current_images.get("morning", "")),
        allow_clear=True,
    )
    evening_image = prompt_with_default(
        "请输入晚上签到图片路径",
        str(current_images.get("evening", "")),
        allow_clear=True,
    )
    updates = prepare_bind_setup_updates(
        account_config,
        address=address,
        default_image=default_image,
        morning_image=morning_image,
        evening_image=evening_image,
    )
    logging.info(
        "地址已解析为经纬度: %s -> lng=%s lat=%s",
        updates["clock_address"],
        updates["lng"],
        updates["lat"],
    )
    return updates


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


def extract_upload_file_id(payload: dict[str, Any]) -> str:
    decoded = decode_sxsx_response(payload)
    if decoded.get("code") != 200:
        raise CheckinError(f"上传图片失败: {decoded}")

    data = decoded.get("data")
    if isinstance(data, dict):
        for key in ("id", "fileId"):
            value = data.get(key)
            if value:
                return str(value)
    for key in ("id", "fileId"):
        value = decoded.get(key)
        if value:
            return str(value)

    raise CheckinError(f"上传成功但未找到文件 ID: {decoded}")


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


def apply_student_plan_context(config: dict[str, Any], plan_data: dict[str, Any]) -> None:
    autonomy_plan = plan_data.get("autonomyPlan")
    if autonomy_plan and autonomy_plan.get("id"):
        config["plan_type"] = "autonomyPlan"
        config["autonomy_id"] = autonomy_plan["id"]
        config["practice_plan_id"] = ""
        return

    practice_plan = plan_data.get("practicePlan")
    if practice_plan and practice_plan.get("planId"):
        config["plan_type"] = "practicePlan"
        config["practice_plan_id"] = practice_plan["planId"]
        config["autonomy_id"] = ""
        return

    config["plan_type"] = ""
    config["autonomy_id"] = ""
    config["practice_plan_id"] = ""
    raise CheckinError(f"当前账号未查询到可用实习计划，请确认登录的是有实习计划的账号. plan_data: {plan_data}")


def is_practice_plan(config: dict[str, Any]) -> bool:
    return config.get("plan_type") == "practicePlan"


def populate_runtime_config(config: dict[str, Any], bearer_token: str, session: requests.Session, user_info: dict[str, Any] | None = None) -> None:
    previous_user_id = str(config.get("user_id") or "")
    user_info = user_info or fetch_user_info(config, bearer_token, session)
    if user_info:
        config["user_id"] = user_info.get("userId") or config.get("user_id", "")
        config["user_name"] = user_info.get("userName") or config.get("user_name", "")
        config["nick_name"] = user_info.get("nickName") or config.get("nick_name", "")
    current_user_id = str(config.get("user_id") or "")
    if previous_user_id and current_user_id and previous_user_id != current_user_id:
        config["autonomy_id"] = ""
        config["practice_plan_id"] = ""
        config["plan_type"] = ""

    plan_data = fetch_student_plan(config, bearer_token, session)
    logging.info(f"Student plan data: {plan_data}")
    apply_student_plan_context(config, plan_data)


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
        config["user_name"] = user_info.get("userName") or config.get("user_name", "")
        config["nick_name"] = user_info.get("nickName") or config.get("nick_name", "")
    populate_runtime_config(config, token, session, user_info=user_info)
    persist_bearer_token(config, token)
    return token


def password_login_unavailable_message() -> str:
    return (
        "旧的 /portal-api/app/index/login 直登已移除。"
        "根据当前 HAR，平台实际使用 app_user_id -> checkAppUserIdNew 换取签到 token；"
        "账号密码登录已切到统一认证并带点选验证码，脚本暂不处理该验证码。"
        "请先手动登录一次获取 app_user_id，之后脚本即可自动换取签到 token。"
    )


def is_token_expired_error(error: Exception) -> bool:
    message = str(error)
    return "code': 401" in message or '"code": 401' in message or "登录信息已过期" in message


def build_auth_authorize_url() -> str:
    params = {
        "response_type": "code",
        "client_id": "rrtapp",
        "redirect_uri": f"{AUTH_BASE_URL}/appauth",
        "scope": "userinfo",
        "themeType": "rrtapp",
        "state": uuid4().hex,
        "isWeixinInstalled": "1",
        "rc": "80800",
    }
    return f"{AUTH_BASE_URL}/api/oauth/oauth2/authorize?{urllib.parse.urlencode(params)}"


def get_system_browser_choice() -> tuple[str, Path]:
    candidates = [
        ("edge", EDGE_BINARY_PATH),
        ("chrome", CHROME_BINARY_PATH),
    ]
    for browser_name, browser_path in candidates:
        if browser_path.exists():
            return browser_name, browser_path
    raise CheckinError("未找到可用的系统浏览器，请先安装 Edge 或 Chrome")


def interactive_auth_login_via_playwright(timeout_seconds: int = 300) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as exc:
        raise CheckinError("缺少 playwright，请先执行: pip install playwright") from exc

    browser = None
    try:
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=False)
            except FileNotFoundError as exc:
                raise CheckinError("Playwright 运行时不完整，无法启动内置浏览器") from exc
            except Exception as exc:
                raise CheckinError(
                    "无法启动 Playwright Chromium。请先执行: playwright install chromium"
                ) from exc

            context = browser.new_context()
            page = context.new_page()
            page.goto(build_auth_authorize_url(), wait_until="domcontentloaded")
            logging.info("浏览器已打开，请在 %s 秒内完成统一认证登录和验证码", timeout_seconds)

            deadline = time.monotonic() + timeout_seconds
            while time.monotonic() < deadline:
                cookies = context.cookies()
                auth_cookies = {
                    cookie["name"]: cookie["value"]
                    for cookie in cookies
                    if "auth.jx.smartedu.cn" in cookie.get("domain", "")
                }
                auth_token = auth_cookies.get("token", "")
                if auth_token:
                    return {
                        "auth_token": auth_token,
                        "cookies": auth_cookies,
                        "final_url": page.url,
                    }
                page.wait_for_timeout(1000)
    finally:
        if browser is not None:
            browser.close()

    raise CheckinError("等待统一认证登录完成超时，请重试")


def interactive_auth_login_via_selenium(timeout_seconds: int = 300) -> dict[str, Any]:
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options as ChromeOptions
        from selenium.webdriver.edge.options import Options as EdgeOptions
    except ModuleNotFoundError as exc:
        raise CheckinError("缺少 selenium，请先执行: pip install selenium") from exc

    browser_name, browser_path = get_system_browser_choice()
    if browser_name == "edge":
        options = EdgeOptions()
        options.binary_location = str(browser_path)
        driver = webdriver.Edge(options=options)
    else:
        options = ChromeOptions()
        options.binary_location = str(browser_path)
        driver = webdriver.Chrome(options=options)

    try:
        driver.get(build_auth_authorize_url())
        logging.info("已打开系统浏览器 %s，请在 %s 秒内完成统一认证登录和验证码", browser_name, timeout_seconds)
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            cookies = {cookie["name"]: cookie["value"] for cookie in driver.get_cookies()}
            auth_token = cookies.get("token", "")
            if auth_token:
                return {
                    "auth_token": auth_token,
                    "cookies": cookies,
                    "final_url": driver.current_url,
                    "browser": browser_name,
                }
            time.sleep(1)
    finally:
        driver.quit()

    raise CheckinError("等待统一认证登录完成超时，请重试")


def interactive_auth_login(timeout_seconds: int = 300) -> dict[str, Any]:
    errors: list[str] = []
    if getattr(sys, "frozen", False):
        try:
            return interactive_auth_login_via_selenium(timeout_seconds=timeout_seconds)
        except Exception as exc:
            errors.append(f"Selenium 失败: {exc}")

    try:
        return interactive_auth_login_via_playwright(timeout_seconds=timeout_seconds)
    except Exception as exc:
        errors.append(f"Playwright 失败: {exc}")
        logging.warning("Playwright 登录流程不可用，尝试回退 Selenium: %s", exc)

    try:
        return interactive_auth_login_via_selenium(timeout_seconds=timeout_seconds)
    except Exception as exc:
        errors.append(f"Selenium 失败: {exc}")

    raise CheckinError("；".join(errors))


def fetch_auth_current_user(auth_state: dict[str, Any], session: requests.Session | None = None) -> dict[str, Any]:
    session = session or requests.Session()
    for name, value in (auth_state.get("cookies") or {}).items():
        session.cookies.set(name, value, domain="auth.jx.smartedu.cn")

    response = session.get(
        f"{AUTH_BASE_URL}/api/oauth/anyone/getUserInfoById",
        headers={
            "token": str(auth_state["auth_token"]),
            "user-agent": AUTH_USER_AGENT,
            "accept": "application/json, text/plain, */*",
        },
        timeout=30,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("code") != 0 or not isinstance(payload.get("data"), dict):
        raise CheckinError(f"统一认证未返回有效用户信息: {payload}")
    return payload["data"]


def bind_account(
    raw_config: dict[str, Any],
    *,
    config_path: Path = DEFAULT_CONFIG_FILE,
    account_name: str | None = None,
    timeout_seconds: int = 300,
) -> dict[str, Any]:
    account_config = get_single_account_config(raw_config, account_name)
    setup_updates = prompt_bind_setup(account_config)
    account_config.update(setup_updates)
    apply_account_updates(raw_config, setup_updates, account_name=account_name)
    save_config(raw_config, config_path)

    auth_state = interactive_auth_login(timeout_seconds=timeout_seconds)
    auth_user = fetch_auth_current_user(auth_state)

    account_config["app_user_id"] = str(auth_user["id"])
    clear_account_identity_fields(account_config)
    if auth_user.get("nickName") and not account_config.get("nick_name"):
        account_config["nick_name"] = str(auth_user["nickName"])
    apply_account_updates(
        raw_config,
        {
            "app_user_id": account_config.get("app_user_id", ""),
            "manual_bearer_token": "",
            "user_id": "",
            "user_name": "",
            "nick_name": account_config.get("nick_name", ""),
            "autonomy_id": "",
            "plan_type": "",
            "practice_plan_id": "",
        },
        account_name=account_name,
        keep_empty=True,
    )
    save_config(raw_config, config_path)

    bearer_token = fetch_sxsx_bearer_token(account_config, requests.Session())
    updates = {
        **setup_updates,
        "app_user_id": account_config.get("app_user_id", ""),
        "manual_bearer_token": account_config.get("manual_bearer_token", ""),
        "user_id": account_config.get("user_id", ""),
        "user_name": account_config.get("user_name", ""),
        "nick_name": account_config.get("nick_name", ""),
        "autonomy_id": account_config.get("autonomy_id", ""),
        "plan_type": account_config.get("plan_type", ""),
        "practice_plan_id": account_config.get("practice_plan_id", ""),
    }
    apply_account_updates(raw_config, updates, account_name=account_name)
    save_config(raw_config, config_path)
    return {**updates, "bearer_token": bearer_token}


def ensure_account_session(
    raw_config: dict[str, Any],
    *,
    config_path: Path = DEFAULT_CONFIG_FILE,
    account_name: str | None = None,
    timeout_seconds: int = 300,
) -> tuple[dict[str, Any], str]:
    account_config = get_single_account_config(raw_config, account_name)
    session = requests.Session()
    try:
        token = get_bearer_token(account_config, session)
        apply_account_updates(
            raw_config,
            {
                "app_user_id": account_config.get("app_user_id", ""),
                "manual_bearer_token": account_config.get("manual_bearer_token", ""),
                "user_id": account_config.get("user_id", ""),
                "user_name": account_config.get("user_name", ""),
                "nick_name": account_config.get("nick_name", ""),
                "autonomy_id": account_config.get("autonomy_id", ""),
                "plan_type": account_config.get("plan_type", ""),
                "practice_plan_id": account_config.get("practice_plan_id", ""),
            },
            account_name=account_name,
        )
        save_config(raw_config, config_path)
        account_config = get_single_account_config(raw_config, account_name)
        return account_config, token
    except CheckinError as exc:
        logging.warning("当前 token 不可用，准备重新绑定: %s", exc)

    bind_account(
        raw_config,
        config_path=config_path,
        account_name=account_name,
        timeout_seconds=timeout_seconds,
    )
    account_config = get_single_account_config(raw_config, account_name)
    session = requests.Session()
    token = get_bearer_token(account_config, session)
    return account_config, token


def get_bearer_token(config: dict[str, Any], session: requests.Session) -> str:
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

    if config.get("app_user_id"):
        try:
            token = fetch_sxsx_bearer_token(config, session)
            logging.info("app_user_id 换取新 token 成功")
            return token
        except Exception as exc:
            errors.append(f"app_user_id 换 token 失败: {exc}")

    if has_direct_login_credentials(config):
        errors.append(password_login_unavailable_message())

    raise CheckinError("；".join(errors) or "没有可用的 token 获取方式")


def get_daily_clocks(
    config: dict[str, Any],
    bearer_token: str,
    query_date: date,
    session: requests.Session,
) -> list[dict[str, Any]]:
    if is_practice_plan(config):
        url = f"{config['sxsx_base_url']}/portal-api/practiceClock/practiceClock/getStuDailyClock"
        params = {
            "planId": config["practice_plan_id"],
            "userId": config["user_id"],
            "queryDate": query_date.strftime("%Y-%m-%d"),
            "beginQueryDate": "",
            "endQueryDate": "",
        }
    else:
        url = f"{config['sxsx_base_url']}/portal-api/practice/autonomyClock/getStuDailyClock"
        params = {
            "autonomyId": config["autonomy_id"],
            "userId": config["user_id"],
            "queryDate": query_date.strftime("%Y-%m-%d"),
            "beginQueryDate": "",
            "endQueryDate": "",
        }
    payload = request_json(
        session,
        "GET",
        url,
        params=params,
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


def should_skip_existing_checkin(
    clocks: list[dict[str, Any]],
    slot: dict[str, Any],
    *,
    skip_if_already_signed: bool,
    force: bool,
) -> bool:
    if not skip_if_already_signed or force:
        return False
    if slot.get("name") == "evening" and len(clocks) == 1:
        return False
    return has_clock_in_slot(clocks, slot)


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
    forced_slot_name = str(config.get("_forced_image_slot") or "")
    slot_name = forced_slot_name or str(slot.get("name") or "")
    slot_path = proof_images.get(slot_name)
    return resolve_local_path(slot_path or config["proof_image_path"])


def image_source_for_slot(config: dict[str, Any], slot: dict[str, Any]) -> str:
    proof_images = config.get("proof_images") or {}
    forced_slot_name = str(config.get("_forced_image_slot") or "")
    slot_name = forced_slot_name or str(slot.get("name") or "")
    return str(proof_images.get(slot_name) or config["proof_image_path"])


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
    image_source = image_source_for_slot(config, slot)
    if is_practice_plan(config):
        url = f"{config['sxsx_base_url']}/portal-api/common/uploadFileUrl"
    else:
        url = f"{config['sxsx_base_url']}/portal-api/practiceClock/practiceClock/uploadClockFile"
    file_name, file_bytes, mime_type = prepare_upload_file(image_source, session, int(config["request_timeout"]))
    response = session.post(
        url,
        headers=build_headers(bearer_token, content_type=None),
        files={"file": (file_name, file_bytes, mime_type)},
        timeout=int(config["request_timeout"]),
    )
    response.raise_for_status()
    if is_practice_plan(config):
        return extract_upload_file_id(response.json())
    return extract_upload_remark(response.json())


def submit_checkin(
    config: dict[str, Any],
    bearer_token: str,
    remark: str,
    session: requests.Session,
    now: datetime,
) -> bool:
    if is_practice_plan(config):
        url = f"{config['sxsx_base_url']}/portal-api/practiceClock/practiceClock/add"
        payload = {
            "planId": config["practice_plan_id"],
            "userId": config["user_id"],
            "userName": config.get("user_name", ""),
            "nickName": config["nick_name"],
            "clockAddress": config["clock_address"],
            "fileId": remark,
            "clockTime": now.strftime("%Y-%m-%d %H:%M:%S"),
            "clockType": config["clock_type"],
            "clockContent": config.get("clock_content", ""),
        }
    else:
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
    if decoded.get("code") != 200:
        logging.error(f"签到提交失败，接口返回: {decoded}")
    return decoded.get("code") == 200


def run_checkin(
    *,
    config: dict[str, Any] | None = None,
    slot_name: str | None = None,
    dry_run: bool = False,
    force: bool = False,
    bearer_token: str | None = None,
) -> bool:
    config = config or load_config()
    now = datetime.now()
    slot = find_slot(config, slot_name, now)
    session = requests.Session()

    logging.info("开始%s: %s", slot.get("label", slot["name"]), now.strftime("%Y-%m-%d %H:%M:%S"))
    logging.info("账户: %s", config.get("name", "default"))
    bearer_token = bearer_token or get_bearer_token(config, session)
    clocks = get_daily_clocks(config, bearer_token, now.date(), session)
    logging.info("今日已有签到记录 %s 条", len(clocks))

    if should_skip_existing_checkin(
        clocks,
        slot,
        skip_if_already_signed=bool(config.get("skip_if_already_signed", True)),
        force=force,
    ):
        logging.info("当前时段已经签到，跳过提交")
        return True
    if slot.get("name") == "evening" and len(clocks) == 1 and has_clock_in_slot(clocks, slot):
        logging.info("当前为晚上且今日仅有 1 条签到记录，允许补签第二次")

    if dry_run:
        logging.info("dry-run 模式：已完成 Token 和记录查询，不上传、不提交")
        return True

    def do_submit(current_token: str) -> bool:
        remark = ""
        if config.get("upload_image", True):
            remark = upload_image(config, current_token, session, slot)
            logging.info("图片上传成功: %s", remark)
            if config.get("verify_uploaded_image", True):
                if not wait_for_uploaded_image(config, remark, session):
                    raise CheckinError(f"图片上传后未能在限定时间内访问: {uploaded_image_url(config, remark)}")
                logging.info("图片已确认可访问")

        if submit_checkin(config, current_token, remark, session, now):
            logging.info("签到成功")
            return True
        return False

    try:
        if do_submit(bearer_token):
            return True
    except CheckinError as exc:
        if not (config.get("app_user_id") and is_token_expired_error(exc)):
            raise
        logging.warning("写接口提示 token 过期，尝试重新换取 token 后重试一次")
        bearer_token = fetch_sxsx_bearer_token(config, requests.Session())
        if do_submit(bearer_token):
            return True

    raise CheckinError("签到接口未返回成功")


def should_run_evening_makeup_double_checkin(slot_name: str, clocks: list[dict[str, Any]]) -> bool:
    return slot_name == "evening" and len(clocks) == 0


def run_slot_now(
    config: dict[str, Any],
    slot_name: str,
    *,
    raw_config: dict[str, Any] | None = None,
    config_path: Path = DEFAULT_CONFIG_FILE,
    bind_timeout: int = 300,
) -> None:
    slot = find_slot(config, slot_name, datetime.now())
    try:
        bearer_token = None
        account_config = config
        if raw_config is not None:
            account_config, bearer_token = ensure_account_session(
                raw_config,
                config_path=config_path,
                account_name=config.get("name"),
                timeout_seconds=bind_timeout,
            )
        if slot_name == "evening":
            session = requests.Session()
            current_token = bearer_token or get_bearer_token(account_config, session)
            clocks = get_daily_clocks(account_config, current_token, datetime.now().date(), session)
            if should_run_evening_makeup_double_checkin(slot_name, clocks):
                logging.info("当前为晚上且今日签到记录为 0，先补早图，再补晚图，两次间隔 10 秒")
                morning_config = deepcopy(account_config)
                morning_config["_forced_image_slot"] = "morning"
                run_checkin(config=morning_config, slot_name="morning", bearer_token=current_token)
                time.sleep(10)
                evening_config = deepcopy(account_config)
                evening_config["_forced_image_slot"] = "evening"
                run_checkin(config=evening_config, slot_name="evening", bearer_token=current_token)
                return
            bearer_token = current_token
        run_checkin(config=account_config, slot_name=slot_name, bearer_token=bearer_token)
    except Exception:
        logging.exception("%s 执行失败", slot.get("label", slot_name))


def run_slot_with_jitter(
    config: dict[str, Any],
    slot_name: str,
    *,
    raw_config: dict[str, Any] | None = None,
    config_path: Path = DEFAULT_CONFIG_FILE,
    bind_timeout: int = 300,
) -> None:
    slot = find_slot(config, slot_name, datetime.now())
    jitter_seconds = max(0, int(slot.get("jitter_minutes", 0))) * 60
    if jitter_seconds:
        delay = random.randint(0, jitter_seconds)
        logging.info("%s 随机延迟 %s 秒后执行", slot.get("label", slot_name), delay)
        time.sleep(delay)
    run_slot_now(
        config,
        slot_name,
        raw_config=raw_config,
        config_path=config_path,
        bind_timeout=bind_timeout,
    )


def run_scheduler(config: dict[str, Any], *, config_path: Path = DEFAULT_CONFIG_FILE, bind_timeout: int = 300) -> None:
    try:
        import schedule
    except ModuleNotFoundError as exc:
        raise CheckinError("缺少依赖 schedule，请先执行: pip install schedule") from exc

    scheduled = 0
    for account_config in iter_account_configs(config):
        for slot in account_config["slots"]:
            schedule.every().day.at(slot["time"]).do(
                run_slot_with_jitter,
                account_config,
                slot["name"],
                raw_config=config,
                config_path=config_path,
                bind_timeout=bind_timeout,
            )
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
    parser.add_argument("--bind-account", action="store_true", help="打开浏览器登录一次并自动绑定 app_user_id")
    parser.add_argument("--bind-timeout", type=int, default=300, help="绑定流程等待登录完成的秒数")
    parser.add_argument("--once", action="store_true", help="立即执行一次签到")
    parser.add_argument(
        "--run-scheduled-slot-now",
        choices=["morning", "evening"],
        help="立即执行一次定时模式同款任务，用于测试补签和调度逻辑",
    )
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
        if args.bind_account:
            bound = bind_account(
                config,
                config_path=config_path,
                account_name=args.account,
                timeout_seconds=args.bind_timeout,
            )
            logging.info(
                "绑定成功: app_user_id=%s user_id=%s autonomy_id=%s",
                bound.get("app_user_id", ""),
                bound.get("user_id", ""),
                bound.get("autonomy_id", ""),
            )
            return 0
        if args.run_scheduled_slot_now:
            account_configs = list(iter_account_configs(config, args.account))
            if not account_configs:
                raise CheckinError(f"未找到账户: {args.account}")
            for account_config in account_configs:
                run_slot_now(
                    account_config,
                    args.run_scheduled_slot_now,
                    raw_config=config,
                    config_path=config_path,
                    bind_timeout=args.bind_timeout,
                )
            return 0
        if args.once or args.dry_run:
            account_names = [account.get("name", "default") for account in iter_account_configs(config, args.account)]
            if not account_names:
                raise CheckinError(f"未找到账户: {args.account}")
            ok = True
            for account_name in account_names:
                account_config, bearer_token = ensure_account_session(
                    config,
                    config_path=config_path,
                    account_name=account_name,
                    timeout_seconds=args.bind_timeout,
                )
                ok = run_checkin(
                    config=account_config,
                    slot_name=args.slot,
                    dry_run=args.dry_run,
                    force=args.force,
                    bearer_token=bearer_token,
                ) and ok
            return 0 if ok else 1
        run_scheduler(config, config_path=config_path, bind_timeout=args.bind_timeout)
        return 0
    except Exception:
        logging.exception("自动签到失败")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
