import json
from pathlib import Path

from app.ai.pipeline import classify_intent, duplicate_score, extract_structured
from app.models import Issue


def test_structured_elevator_extraction():
    result = extract_structured("лифт опять встал во втором подъезде")
    assert result.intent == "issue"
    assert result.category == "elevator"
    assert result.zone.number == "2"
    assert result.recurrence_hint is True


def test_initiative_and_confirmation_classification():
    assert classify_intent("на парковке нужен второй фонарь") == "initiative"
    assert classify_intent("у меня тоже") == "confirmation"


def test_duplicate_requires_matching_context():
    issue = Issue(house_id="a", zone_id="entrance-1", asset_id="lift-1", category="elevator", title="Лифт", description="лифт не работает")
    same = duplicate_score(issue, house_id="a", zone_id="entrance-1", asset_id="lift-1", category="elevator", text="лифт сломан")
    other_entrance = duplicate_score(issue, house_id="a", zone_id="entrance-2", asset_id="lift-2", category="elevator", text="лифт сломан")
    other_house = duplicate_score(issue, house_id="b", zone_id="entrance-1", asset_id="lift-1", category="elevator", text="лифт сломан")
    assert same > 0.78
    assert other_entrance < 0.5
    assert other_house == 0


def test_ai_eval_dataset_targets():
    records = [json.loads(line) for line in Path("datasets/house_chat_eval/eval.jsonl").read_text().splitlines() if line]
    intent_correct = sum(classify_intent(item["text"]) == item["intent"] for item in records)
    category_records = [item for item in records if item.get("category")]
    category_correct = sum(extract_structured(item["text"]).category == item["category"] for item in category_records)
    assert intent_correct / len(records) >= 0.90
    assert category_correct / len(category_records) >= 0.90

