import hashlib
import hmac
import json
from urllib.parse import urlencode

import pytest

from app.integrations.max_init_data import MaxInitDataError, validate_max_init_data


TOKEN = "test-token"
NOW = 1_780_000_000


def signed_init_data(**overrides):
    values = {
        "auth_date": str(NOW),
        "chat": json.dumps({"id": 77, "type": "CHAT"}, separators=(",", ":")),
        "query_id": "query-1",
        "start_param": "issue_demo-issue",
        "user": json.dumps({"id": 42, "first_name": "Анна"}, ensure_ascii=False, separators=(",", ":")),
    }
    values.update(overrides)
    launch_params = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, launch_params.encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


def test_validates_signed_max_context():
    result = validate_max_init_data(signed_init_data(), TOKEN, now=NOW + 10)
    assert result["valid"] is True
    assert result["user"]["id"] == 42
    assert result["chat"] == {"id": 77, "type": "CHAT"}
    assert result["start_param"] == "issue_demo-issue"


def test_rejects_modified_or_expired_context():
    modified = signed_init_data().replace("query-1", "query-2")
    with pytest.raises(MaxInitDataError, match="signature"):
        validate_max_init_data(modified, TOKEN, now=NOW + 10)
    with pytest.raises(MaxInitDataError, match="expired"):
        validate_max_init_data(signed_init_data(), TOKEN, now=NOW + 3601)


def test_rejects_duplicate_hash():
    with pytest.raises(MaxInitDataError, match="duplicate"):
        validate_max_init_data(f"{signed_init_data()}&hash=again", TOKEN, now=NOW)
