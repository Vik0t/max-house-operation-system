import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Asset, Issue, Zone
from ..schemas import ExtractedZone, StructuredExtraction


ISSUE_KEYWORDS = {
    "elevator": ("лифт", "застрял", "кабина"),
    "lighting": ("свет", "ламп", "фонар"),
    "water": ("вод", "теч", "протеч"),
    "heating": ("отоп", "батар", "холодно"),
    "cleaning": ("гряз", "уборк", "мусор"),
    "door": ("двер", "домофон", "замок"),
}
INITIATIVE_MARKERS = ("нужно", "предлагаю", "поставить", "установить", "давайте", "хотелось", "второй фонарь")
CONFIRM_MARKERS = ("у меня тоже", "тоже не", "подтверждаю", "да, не работает")
RECURRENCE_MARKERS = ("опять", "снова", "уже", "вчера", "третий раз", "повтор")


class AIPipelineUnavailable(RuntimeError):
    pass


def detect_actionability(text: str) -> tuple[bool, float]:
    lowered = text.lower()
    matches = sum(keyword in lowered for values in ISSUE_KEYWORDS.values() for keyword in values)
    matches += sum(marker in lowered for marker in INITIATIVE_MARKERS)
    score = min(0.99, 0.2 + matches * 0.22)
    return matches > 0 or any(marker in lowered for marker in CONFIRM_MARKERS), score


def classify_intent(text: str) -> str:
    lowered = text.lower()
    if any(marker in lowered for marker in CONFIRM_MARKERS):
        return "confirmation"
    if any(marker in lowered for marker in INITIATIVE_MARKERS) and not any(
        broken in lowered for broken in ("не работает", "слом", "перегор", "теч")
    ):
        return "initiative"
    actionable, _ = detect_actionability(text)
    return "issue" if actionable else "noise"


def extract_structured(text: str, *, force_failure: bool = False) -> StructuredExtraction:
    if force_failure:
        raise AIPipelineUnavailable("Injected AI timeout")
    lowered = text.lower().strip()
    actionable, score = detect_actionability(lowered)
    intent = classify_intent(lowered)
    category = "other"
    for candidate, keywords in ISSUE_KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            category = candidate
            break
    number_match = re.search(r"(?:подъезд[ае]?|подъезде|подъезда|втор(?:ой|ого)|№)\s*(\d+)", lowered)
    ordinal_map = {"перв": "1", "втор": "2", "трет": "3", "четвер": "4"}
    zone_number = number_match.group(1) if number_match else next(
        (number for prefix, number in ordinal_map.items() if prefix in lowered and "подъезд" in lowered), None
    )
    zone_type = "parking" if "парков" in lowered else ("entrance" if "подъезд" in lowered or zone_number else None)
    symptom = "not_working" if any(word in lowered for word in ("не работает", "встал", "слом", "перегор")) else "proposal"
    missing: list[str] = []
    if intent == "issue" and not zone_type:
        missing.append("zone")
    return StructuredExtraction(
        actionable=actionable,
        intent=intent,  # type: ignore[arg-type]
        category=category,
        zone=ExtractedZone(type=zone_type, number=zone_number),
        asset_hint=category if category != "other" else None,
        symptom=symptom,
        recurrence_hint=any(marker in lowered for marker in RECURRENCE_MARKERS),
        missing_fields=missing,
        confidence=max(0.35, score),
    )


@dataclass(frozen=True)
class Resolution:
    zone: Zone | None
    asset: Asset | None
    confidence: float
    needs_clarification: bool


def resolve_zone_asset(db: Session, house_id: str, extraction: StructuredExtraction) -> Resolution:
    zones = db.scalars(select(Zone).where(Zone.house_id == house_id)).all()
    zone = next(
        (
            item
            for item in zones
            if item.type == extraction.zone.type
            and (not extraction.zone.number or item.number == extraction.zone.number)
        ),
        None,
    )
    if not zone and extraction.zone.type == "parking":
        zone = next((item for item in zones if "парков" in item.name.lower() or item.type == "yard"), None)
    assets = db.scalars(select(Asset).where(Asset.house_id == house_id)).all()
    candidates = [item for item in assets if not zone or item.zone_id == zone.id]
    asset = next((item for item in candidates if item.type == extraction.asset_hint), None)
    if not asset and extraction.asset_hint:
        fuzzy_asset = max(
            candidates,
            key=lambda item: SequenceMatcher(None, item.type, extraction.asset_hint or "").ratio(),
            default=None,
        )
        # A fuzzy match may resolve spelling variants, but must never turn a
        # lighting/water signal into an unrelated elevator just because it is
        # the only asset in that zone. Low confidence stays unresolved.
        if fuzzy_asset and SequenceMatcher(None, fuzzy_asset.type, extraction.asset_hint or "").ratio() >= 0.8:
            asset = fuzzy_asset
    confidence = 0.95 if zone and asset else (0.7 if zone else 0.35)
    return Resolution(zone=zone, asset=asset, confidence=confidence, needs_clarification=zone is None)


def semantic_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left.lower(), right.lower()).ratio()


def duplicate_score(existing: Issue, *, house_id: str, zone_id: str | None, asset_id: str | None, category: str, text: str) -> float:
    if existing.house_id != house_id:
        return 0.0
    if existing.category != category:
        return 0.0
    score = 0.15
    score += 0.25 if existing.zone_id and existing.zone_id == zone_id else 0
    score += 0.35 if existing.asset_id and existing.asset_id == asset_id else 0
    score += 0.15 if existing.category == category else 0
    score += 0.10 * semantic_similarity(existing.description, text)
    return round(score, 3)
