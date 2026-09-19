import hashlib
import hmac
import json
import time
from typing import Any
from urllib.parse import parse_qsl


class MaxInitDataError(ValueError):
    pass


def validate_max_init_data(
    init_data: str,
    bot_token: str,
    *,
    max_age_seconds: int = 3600,
    now: int | None = None,
) -> dict[str, Any]:
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise MaxInitDataError("Malformed MAX init data") from exc
    keys = [key for key, _ in pairs]
    if len(keys) != len(set(keys)) or keys.count("hash") != 1:
        raise MaxInitDataError("MAX init data contains duplicate or missing fields")
    received_hash = dict(pairs)["hash"]
    launch_params = "\n".join(f"{key}={value}" for key, value in sorted(pairs) if key != "hash")
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    expected_hash = hmac.new(secret_key, launch_params.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(received_hash, expected_hash):
        raise MaxInitDataError("Invalid MAX init data signature")
    raw = dict(pairs)
    try:
        auth_date = int(raw["auth_date"])
    except (KeyError, TypeError, ValueError) as exc:
        raise MaxInitDataError("MAX auth_date is missing or invalid") from exc
    current_time = int(time.time()) if now is None else now
    if auth_date > current_time + 60 or current_time - auth_date > max_age_seconds:
        raise MaxInitDataError("MAX init data has expired")
    result: dict[str, Any] = {"valid": True, "auth_date": auth_date}
    for key in ("user", "chat"):
        if raw.get(key):
            try:
                result[key] = json.loads(raw[key])
            except json.JSONDecodeError as exc:
                raise MaxInitDataError(f"MAX {key} is invalid") from exc
    if raw.get("start_param"):
        result["start_param"] = raw["start_param"]
    if raw.get("query_id"):
        result["query_id"] = raw["query_id"]
    return result
