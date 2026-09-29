"""Pure-Python inference for a data-only TF-IDF/logistic-regression artifact.

No pickle/joblib is loaded in the public API process.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from functools import lru_cache
from pathlib import Path


MODEL_PATH = Path(__file__).resolve().parents[4] / "models" / "category_char_lr.json"


@lru_cache(maxsize=1)
def load_model() -> dict | None:
    try:
        model = json.loads(MODEL_PATH.read_text(encoding="utf-8"))
        if model.get("kind") != "tfidf_char_lr" or len(model["classes"]) != len(model["coef"]):
            return None
        return model
    except (OSError, ValueError, KeyError, TypeError):
        return None


def vectorize(text: str, model: dict) -> dict[int, float]:
    text = text.lower()
    vocabulary = model["vocabulary"]
    counts: Counter[int] = Counter()
    for size in range(2, 5):
        for offset in range(len(text) - size + 1):
            index = vocabulary.get(text[offset:offset + size])
            if index is not None:
                counts[index] += 1
    values = {index: (1 + math.log(count)) * model["idf"][index] for index, count in counts.items()}
    norm = math.sqrt(sum(value * value for value in values.values()))
    return {index: value / norm for index, value in values.items()} if norm else {}


def predict_category(text: str) -> tuple[str, float] | None:
    model = load_model()
    if not model:
        return None
    features = vectorize(text, model)
    if not features:
        return None
    logits = [bias + sum(weights[index] * value for index, value in features.items()) for bias, weights in zip(model["intercept"], model["coef"])]
    shift = max(logits)
    exp = [math.exp(value - shift) for value in logits]
    probabilities = [value / sum(exp) for value in exp]
    winner = max(range(len(probabilities)), key=probabilities.__getitem__)
    return model["classes"][winner], probabilities[winner]


def trained_similarity(left: str, right: str) -> float | None:
    model = load_model()
    if not model:
        return None
    left_vector = vectorize(left, model)
    right_vector = vectorize(right, model)
    return sum(value * right_vector.get(index, 0.0) for index, value in left_vector.items())
