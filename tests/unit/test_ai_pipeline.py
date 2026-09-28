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


def test_broken_object_outside_the_six_categories_is_still_a_report():
    # A resident writing "окно разбито" expects a card, not silence. The category
    # stays "other" and the bot then asks only for the location.
    result = extract_structured("окно разбито")
    assert result.intent == "issue"
    assert result.actionable is True
    assert result.category == "other"
    assert result.symptom == "not_working"
    assert result.missing_fields == ["zone"]


def test_leak_reports_are_recognized_as_issues():
    # "потолок протекает" used to be noise: neither the water keywords ("теч"
    # does not match "протекает") nor the broken markers covered it.
    result = extract_structured("потолок протекает над колясочной")
    assert result.intent == "issue"
    assert result.actionable is True
    assert result.symptom == "not_working"
    assert classify_intent("соседи сверху затопили ванную") == "issue"
    # ...but the new markers must not fire on ordinary chatter.
    assert classify_intent("привет всем") == "noise"


def test_breakage_words_do_not_turn_small_talk_into_a_report():
    assert classify_intent("привет всем") == "noise"
    assert classify_intent("кто идёт в магазин") == "noise"
    # "встал" alone is not a breakage marker, otherwise waking up would be a report.
    assert classify_intent("я встал утром и пошёл на работу") == "noise"
    # "разобрать" must not match the "разбит" family.
    assert classify_intent("давайте разберём мусор в подвале") == "initiative"


def test_common_house_objects_now_map_to_a_category():
    assert extract_structured("кран течёт на кухне").category == "water"
    assert extract_structured("не горит освещение на площадке").category == "lighting"
    assert extract_structured("ворота в гараж заклинило").category == "door"


def test_ai_eval_dataset_targets():
    # The dataset is UTF-8. Without an explicit encoding Windows reads it as
    # cp1251, every Cyrillic word turns into mojibake and nothing matches.
    records = [json.loads(line) for line in Path("datasets/house_chat_eval/eval.jsonl").read_text(encoding="utf-8").splitlines() if line]
    intent_correct = sum(classify_intent(item["text"]) == item["intent"] for item in records)
    category_records = [item for item in records if item.get("category")]
    category_correct = sum(extract_structured(item["text"]).category == item["category"] for item in category_records)
    assert intent_correct / len(records) >= 0.90
    assert category_correct / len(category_records) >= 0.90

