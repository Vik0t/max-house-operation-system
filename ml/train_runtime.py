"""Train a small, reproducible category model and export data-only JSON.

The repository's 350-row dataset is one-class for intent, so this script
honestly trains *category only*. Test chats are held out before fitting.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, classification_report, f1_score
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import make_pipeline


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "dataset.csv"
MODEL = ROOT / "models" / "category_char_lr.json"
REPORT = ROOT / "reports" / "category_eval.json"


def rows():
    with DATA.open(encoding="utf-8", newline="") as stream:
        return [row for row in csv.DictReader(stream) if row["text"].strip() and row["category"].strip()]


def main() -> None:
    data = rows()
    texts = [row["text"] for row in data]
    labels = [row["category"] for row in data]
    groups = [row["chat_id"] for row in data]
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=42)
    train_index, test_index = next(splitter.split(texts, labels, groups))
    pipeline = make_pipeline(
        TfidfVectorizer(analyzer="char", ngram_range=(2, 4), min_df=2, max_features=4000, sublinear_tf=True),
        LogisticRegression(max_iter=2000, class_weight="balanced", C=2.0),
    )
    pipeline.fit([texts[i] for i in train_index], [labels[i] for i in train_index])
    expected = [labels[i] for i in test_index]
    predicted = pipeline.predict([texts[i] for i in test_index]).tolist()
    report = {
        "source": "dataset.csv; all examples are intent=issue; synthetic/curated, not live resident traffic",
        "train_rows": len(train_index),
        "test_rows": len(test_index),
        "train_chats": len({groups[i] for i in train_index}),
        "test_chats": len({groups[i] for i in test_index}),
        "overlapping_chats": len({groups[i] for i in train_index} & {groups[i] for i in test_index}),
        "test_support": dict(Counter(expected)),
        "accuracy": round(float(accuracy_score(expected, predicted)), 4),
        "macro_f1": round(float(f1_score(expected, predicted, average="macro")), 4),
        "per_class": classification_report(expected, predicted, output_dict=True, zero_division=0),
    }
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Refit on all available chats for the runtime artifact. This does not
    # change the held-out metrics above; retraining is called out explicitly.
    pipeline.fit(texts, labels)
    vectorizer = pipeline.named_steps["tfidfvectorizer"]
    classifier = pipeline.named_steps["logisticregression"]
    artifact = {
        "kind": "tfidf_char_lr",
        "source": "dataset.csv",
        "classes": classifier.classes_.tolist(),
        "vocabulary": {token: int(index) for token, index in vectorizer.vocabulary_.items()},
        "idf": [round(float(value), 8) for value in vectorizer.idf_],
        "coef": [[round(float(value), 8) for value in row] for row in classifier.coef_],
        "intercept": [round(float(value), 8) for value in classifier.intercept_],
        "ngram_range": [2, 4],
        "sublinear_tf": True,
    }
    MODEL.parent.mkdir(exist_ok=True)
    MODEL.write_text(json.dumps(artifact, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"held-out category accuracy={report['accuracy']:.4f}, macro-F1={report['macro_f1']:.4f}")
    print(f"train/test chats={report['train_chats']}/{report['test_chats']}, overlap={report['overlapping_chats']}")
    print(f"runtime model: {MODEL}")


if __name__ == "__main__":
    main()
