# -*- coding: utf-8 -*-
"""
Запуск:
    python train_baseline.py --data dataset.csv
"""
from __future__ import annotations

import argparse

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.pipeline import Pipeline

CONFIDENCE_THRESHOLD = 0.55

def chat_aware_split(df: pd.DataFrame, test_frac: float = 0.2, dev_frac: float = 0.15):
    chats = df["chat_id"].unique().tolist()
    chats.sort()
    n_test = max(1, int(len(chats) * test_frac))
    n_dev = max(1, int(len(chats) * dev_frac))

    test_chats = set(chats[:n_test])
    dev_chats = set(chats[n_test:n_test + n_dev])

    is_test = df["chat_id"].isin(test_chats)
    is_dev = df["chat_id"].isin(dev_chats) & ~is_test

    test_df = df[is_test]
    dev_df = df[is_dev]
    train_df = df[~is_test & ~is_dev]
    return train_df, dev_df, test_df


def make_pipeline(calibrate: bool = True) -> Pipeline:
    base_clf = LogisticRegression(max_iter=2000, class_weight="balanced")
    if calibrate:
        clf = CalibratedClassifierCV(base_clf, method="sigmoid", cv=3)
    else:
        clf = base_clf
    return Pipeline([
        ("tfidf", TfidfVectorizer(
            analyzer="char_wb",
            ngram_range=(2, 5),
            min_df=2,
        )),
        ("clf", clf),
    ])


def train_and_eval(train_df: pd.DataFrame, dev_df: pd.DataFrame, test_df: pd.DataFrame,
                    target_col: str, label: str) -> Pipeline:
    X_train, y_train = train_df["text"], train_df[target_col]
    X_test, y_test = test_df["text"], test_df[target_col]

    pipe = make_pipeline()
    pipe.fit(X_train, y_train)

    preds = pipe.predict(X_test)
    print(f"\n=== {label} ({target_col}) — отчёт на test ===")
    print(classification_report(y_test, preds, zero_division=0))

    if len(dev_df):
        dev_preds = pipe.predict(dev_df["text"])
        print(f"--- {label} ({target_col}) — отчёт на dev ---")
        print(classification_report(dev_df[target_col], dev_preds, zero_division=0))

    proba = pipe.predict_proba(X_test)
    max_conf = proba.max(axis=1)
    uncertain_share = float(np.mean(max_conf < CONFIDENCE_THRESHOLD))
    print(f"Доля неуверенных предсказаний на test (conf < {CONFIDENCE_THRESHOLD}): "
          f"{uncertain_share:.0%}")

    return pipe


def predict_with_confidence(pipe: Pipeline, texts: list[str], threshold: float = CONFIDENCE_THRESHOLD):
    proba = pipe.predict_proba(texts)
    classes = pipe.classes_
    results = []
    for row in proba:
        best_idx = row.argmax()
        conf = row[best_idx]
        label = classes[best_idx] if conf >= threshold else "uncertain"
        results.append((label, float(conf)))
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=str, default="dataset.csv")
    parser.add_argument("--out_intent", type=str, default="model_intent.joblib")
    parser.add_argument("--out_category", type=str, default="model_category.joblib")
    parser.add_argument("--out_zone_type", type=str, default="model_zone_type.joblib")
    args = parser.parse_args()

    df = pd.read_csv(args.data)
    df = df.dropna(subset=["text", "intent", "category"])
    df["zone_type"] = df["zone_type"].fillna("none")

    train_df, dev_df, test_df = chat_aware_split(df)
    print(f"train: {len(train_df)} строк, dev: {len(dev_df)} строк, test: {len(test_df)} строк "
          f"(из {df['chat_id'].nunique()} чатов)")

    intent_model = train_and_eval(train_df, dev_df, test_df, "intent", "Классификатор intent")
    category_model = train_and_eval(train_df, dev_df, test_df, "category", "Классификатор category")
    zone_type_model = train_and_eval(train_df, dev_df, test_df, "zone_type", "Классификатор zone_type")

    joblib.dump(intent_model, args.out_intent)
    joblib.dump(category_model, args.out_category)
    joblib.dump(zone_type_model, args.out_zone_type)
    print(f"\nМодели сохранены: {args.out_intent}, {args.out_category}, {args.out_zone_type}")

    demo_texts = [
        "лифт опять не едет во втором подъезде",
        "у меня тоже такая же ерунда",
        "давайте лавочку поставим у дома",
        "видели объявление про субботник?",
        "ну наверное тоже самое, не помню точно где",
    ]
    print("\nПримеры предсказаний")
    intent_preds = predict_with_confidence(intent_model, demo_texts)
    category_preds = predict_with_confidence(category_model, demo_texts)
    zone_preds = predict_with_confidence(zone_type_model, demo_texts)
    for text, (i, ic), (c, cc), (z, zc) in zip(demo_texts, intent_preds, category_preds, zone_preds):
        print(f"{text!r:55} -> intent={i} ({ic:.2f}), category={c} ({cc:.2f}), zone_type={z} ({zc:.2f})")


if __name__ == "__main__":
    main()