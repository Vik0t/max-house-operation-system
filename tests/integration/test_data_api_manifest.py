"""Keep the submission API checks executable against a clean local demo DB."""

import json
import re
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
VARIABLES = {
    "MAX_INIT_DATA_RESIDENT": "local-demo-init-data",
    "MAX_INIT_DATA_REPRESENTATIVE": "local-demo-init-data",
    "MAX_INIT_DATA_UK": "local-demo-init-data",
    "MAX_INIT_DATA_EXECUTOR": "local-demo-init-data",
    "MAX_USER_ID_RESIDENT": "resident-jury-test",
    "MAX_USER_ID_REPRESENTATIVE": "representative-demo",
    "MAX_USER_ID_UK": "uk-demo",
    "MAX_USER_ID_EXECUTOR": "master-demo",
}


def resolve(value, variables):
    if isinstance(value, str):
        return re.sub(r"\$\{([A-Za-z_][A-Za-z_0-9]*)\}", lambda match: str(variables[match.group(1)]), value)
    if isinstance(value, list):
        return [resolve(item, variables) for item in value]
    if isinstance(value, dict):
        return {key: resolve(item, variables) for key, item in value.items()}
    return value


def nested_value(payload, expression):
    current = payload
    for part in expression.replace("[", ".").replace("]", "").split("."):
        current = current[int(part)] if isinstance(current, list) else current[part]
    return current


def test_submission_manifest_matches_openapi_and_runs_on_clean_seed(client):
    manifest = yaml.safe_load((ROOT / "DATA-API.yaml").read_text(encoding="utf-8"))
    test_data = json.loads((ROOT / manifest["test_data"]["file"]).read_text(encoding="utf-8"))
    static_openapi = json.loads((ROOT / "openapi.json").read_text(encoding="utf-8"))
    assert manifest["version"] == 1
    assert manifest["name"] == "Дом.Среда"
    assert manifest["base_url"].startswith("https://")
    assert test_data["primary_issue"]["id"] == manifest["test_data"]["issue_id"]
    assert test_data["primary_asset"]["id"] == manifest["test_data"]["asset_id"]
    assert test_data["initiative"]["id"] == manifest["test_data"]["initiative_id"]
    assert static_openapi["openapi"].startswith("3.")
    assert static_openapi == client.get("/openapi.json").json()

    variables = dict(VARIABLES)
    for check in manifest["checks"] + manifest["write_scenarios"]:
        method = check["method"].lower()
        assert method in static_openapi["paths"][check["path"]], check["id"]
        assert set(check["request"]) == {"path_params", "query", "headers", "body"}
        assert check["role"] in {"public", "resident", "representative", "uk", "executor"}
        assert check["expected_status_codes"]
        assert check["expected_response"]["content_type"] == "application/json"

        request = resolve(check["request"], variables)
        path = check["path"].format(**request["path_params"])
        response = client.request(
            check["method"],
            path,
            params=request["query"],
            headers=request["headers"],
            json=request["body"] if method != "get" else None,
        )
        assert response.status_code in check["expected_status_codes"], (check["id"], response.text)
        assert response.headers["content-type"].startswith("application/json")
        payload = response.json()
        expected = check["expected_response"]
        assert isinstance(payload, dict if expected["json_type"] == "object" else list)
        for field in expected.get("required_fields", []):
            assert field in payload, (check["id"], field)
        for item in payload if isinstance(payload, list) else []:
            for field in expected.get("item_required_fields", []):
                assert field in item, (check["id"], field)
        for field, value in expected.get("field_values", {}).items():
            assert nested_value(payload, field) == value, (check["id"], field)
        for variable, field in check.get("capture", {}).items():
            variables[variable] = nested_value(payload, field)
