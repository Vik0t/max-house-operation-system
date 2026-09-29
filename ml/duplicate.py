# -*- coding: utf-8 -*-
"""
Запуск:
    python ml/duplicate.py --data dataset.csv
    python ml/duplicate.py --data dataset.csv --turbo
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics import average_precision_score, roc_auc_score
from sklearn.metrics.pairwise import cosine_similarity

HIGH = 0.75            # >= HIGH -> LINK
LOW  = 0.50            # >= LOW  -> ASK
W_TEXT   = 0.6
W_STRUCT = 0.4
CONFLICT_PENALTY = 0.3

# минимальный зазор между HIGH и LOW при авто-подборе
LOW_GAP = 0.15
# минимальный HIGH
HIGH_FLOOR = 0.30
# целевая precision для авто-LINK
LINK_PRECISION_TARGET = 0.95

# Данные
@dataclass
class Ticket:
    id: str
    text: str
    category: str
    zone_number: str | None = None
    asset_number: str | None = None

def _known(v) -> bool:
    return v is not None and not (isinstance(v, float) and np.isnan(v)) and v != ""

# Бэкенды
class TfidfBackend:
    name = "tfidf"

    def __init__(self):
        self.vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5))

    def fit(self, corpus: list[str]):
        self.vec.fit(corpus)
        return self

    def encode(self, texts: list[str]):
        return self.vec.transform(texts)

class TurboBackend:
    name = "turbo"

    def __init__(self, model_name: str = "sergeyzh/rubert-tiny-turbo"):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(model_name)

    def fit(self, corpus: list[str]):
        return self

    def encode(self, texts: list[str]):
        return self.model.encode(texts, normalize_embeddings=True)

# Скоринг
def structural_score(new: Ticket, cand: Ticket) -> tuple[float, bool]:
    matches, conflict = [], False
    for a, b in ((new.zone_number, cand.zone_number),
                 (new.asset_number, cand.asset_number)):
        if _known(a) and _known(b):
            if str(a) == str(b):
                matches.append(1.0)
            else:
                matches.append(0.0)
                conflict = True
    struct = float(np.mean(matches)) if matches else 0.3
    return struct, conflict

def combine(text_sim: float, new: Ticket, cand: Ticket) -> float:
    if new.category != cand.category:
        return 0.0
    struct, conflict = structural_score(new, cand)
    score = W_TEXT * text_sim + W_STRUCT * struct
    if conflict:
        score *= CONFLICT_PENALTY
    return float(score)

def decide(score: float, high: float | None = None, low: float | None = None) -> str:
    high = HIGH if high is None else high
    low  = LOW  if low  is None else low
    return "LINK" if score >= high else "ASK" if score >= low else "NEW"

# Ранжирование
class DuplicateRanker:
    def __init__(self, backend, use_structure: bool = True,
                 high: float | None = None, low: float | None = None):
        self.backend = backend
        self.use_structure = use_structure
        self.high = high
        self.low  = low

    def rank(self, new: Ticket, candidates: list[Ticket]):
        if not candidates:
            return []
        vecs = self.backend.encode([new.text] + [c.text for c in candidates])
        sims = cosine_similarity(vecs[0:1], vecs[1:])[0]
        out = []
        for cand, sim in zip(candidates, sims):
            score = combine(float(sim), new, cand) if self.use_structure else float(sim)
            out.append({
                "id": cand.id, "text": cand.text,
                "text_sim": round(float(sim), 3),
                "score": round(score, 3),
                "decision": decide(score, self.high, self.low),
            })
        return sorted(out, key=lambda r: r["score"], reverse=True)


# Оценка + авто-порог
# def build_pairs(df: pd.DataFrame):
#     iss = df[df.intent == "issue"].copy()
#     iss = iss[iss.category.notna()]
#     tickets = {}
#     for i, r in iss.iterrows():
#         tickets[i] = Ticket(
#             str(i), r.text, r.category,
#             None if pd.isna(r.zone_number)  else str(int(float(r.zone_number))),
#             None if pd.isna(r.asset_number) else str(int(float(r.asset_number))),
#         )
#     pairs = []
#     for chat, g in iss.groupby("chat_id"):
#         idx = list(g.index)
#         for a in range(len(idx)):
#             for b in range(a + 1, len(idx)):
#                 ta, tb = tickets[idx[a]], tickets[idx[b]]
#                 if ta.category != tb.category: continue
#                 if not (_known(ta.zone_number) and _known(tb.zone_number)): continue
#                 truth = (ta.zone_number == tb.zone_number and
#                          ta.asset_number == tb.asset_number)
#                 pairs.append((ta, tb, truth))
#     return pairs

def build_pairs(df: pd.DataFrame, neg_per_pos: int = 1, seed: int = 42):
    """
    пары
      - truth=True  — сообщения из одной проблемы (дубли)
      - truth=False — сообщения из разных проблем с разными зоной/объектом
    """
    rng = np.random.default_rng(seed)

    iss = df[df.intent == "issue"].copy()
    iss = iss[iss.category.notna()]

    tickets = {}
    for i, r in iss.iterrows():
        tickets[i] = Ticket(
            str(i), r.text, r.category,
            None if pd.isna(r.zone_number)  else str(int(float(r.zone_number))),
            None if pd.isna(r.asset_number) else str(int(float(r.asset_number))),
        )

    groups = {pid: list(g.index) for pid, g in iss.groupby("chat_id")}
    pids = list(groups.keys())

    positives = []
    for pid, idx in groups.items():
        for a in range(len(idx)):
            for b in range(a + 1, len(idx)):
                positives.append((tickets[idx[a]], tickets[idx[b]], True))

    negatives = []
    for i in range(len(pids)):
        for j in range(i + 1, len(pids)):
            pa, pb = pids[i], pids[j]
            a0 = tickets[groups[pa][0]]
            b0 = tickets[groups[pb][0]]

            if a0.category != b0.category:
                continue

            same_zone = (
                _known(a0.zone_number) and _known(b0.zone_number) and
                a0.zone_number == b0.zone_number and
                a0.asset_number == b0.asset_number
            )
            if same_zone:
                continue

            ia = rng.choice(groups[pa])
            ib = rng.choice(groups[pb])
            negatives.append((tickets[ia], tickets[ib], False))

    rng.shuffle(negatives)
    max_neg = len(positives) * neg_per_pos
    negatives = negatives[:max_neg]

    pairs = positives + negatives
    rng.shuffle(pairs)
    return pairs

def _sweep(scores, truth):
    rows = []
    for thr in np.arange(0.05, 0.96, 0.01):
        pred = scores >= thr
        tp = int((pred &  truth).sum()); fp = int((pred & ~truth).sum())
        fn = int((~pred & truth).sum())
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * r / (p + r) if p + r else 0.0
        rows.append({"thr": float(thr), "p": p, "r": r, "f1": f1,
                     "tp": tp, "fp": fp, "fn": fn})
    return rows

def evaluate(pairs, ranker: DuplicateRanker, label: str) -> dict:
    scores = np.array([ranker.rank(a, [b])[0]["score"] for a, b, _ in pairs])
    truth  = np.array([t for _, _, t in pairs])

    pr  = average_precision_score(truth, scores) if truth.any() else 0.0
    roc = roc_auc_score(truth, scores) if truth.any() and (~truth).any() else 0.0

    rows = _sweep(scores, truth)
    n_pos = int(truth.sum())

    # лучший F1
    best_f1 = max(rows, key=lambda r: r["f1"])

    link_candidates = [r for r in rows if r["p"] >= LINK_PRECISION_TARGET and r["tp"] > 0]
    if link_candidates:
        link = link_candidates[-1]
        link_thr = link["thr"]
    else:
        link_thr = best_f1["thr"]

    link_thr = max(link_thr, HIGH_FLOOR)

    auto = scores >= link_thr
    fp_at_link = int((auto & ~truth).sum())

    print(f"{label:38} "
          f"F1={best_f1['f1']:.2f} (P={best_f1['p']:.2f}, R={best_f1['r']:.2f}, "
          f"thr={best_f1['thr']:.2f})  "
          f"PR-AUC={pr:.2f}  ROC-AUC={roc:.2f}  |  "
          f"LINK>={link_thr:.2f}: FP={fp_at_link}/{int(auto.sum())}  ")

    return {"f1_thr": best_f1["thr"], "link_thr": link_thr,
            "pr_auc": pr, "roc_auc": roc,
            "f1": best_f1["f1"], "p": best_f1["p"], "r": best_f1["r"]}

# Демо
def demo(backend, label: str, high: float, low: float):
    cands = [
        Ticket("A", "лифт не работает в первом подъезде", "elevator", "1"),
        Ticket("B", "лифт опять встал во втором подъезде", "elevator", "2"),
        Ticket("C", "лифт застрял между этажами",          "elevator", None),
        Ticket("D", "течёт труба в подвале",               "water",    None),
    ]
    new = Ticket("NEW", "лифт не ездит в 1 подьезде", "elevator", "1")
    print(f"\n--- {label}: новое сообщение {new.text!r} "
          f"(HIGH={high:.2f}, LOW={low:.2f}) ---")
    ranker = DuplicateRanker(backend, use_structure=True, high=high, low=low)
    for r in ranker.rank(new, cands):
        print(f"  {r['id']}: score={r['score']:.2f} "
              f"(текст={r['text_sim']:.2f}) {r['decision']:4} | {r['text']}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="dataset.csv")
    ap.add_argument("--turbo", action="store_true",
                    help="дополнительно прогнать sergeyzh/rubert-tiny-turbo")
    args = ap.parse_args()

    global HIGH, LOW

    df = pd.read_csv(args.data)
    pairs = build_pairs(df)
    print(f"Оценка на {len(pairs)} парах (истина = совпали зона и объект):")

    # turbo
    if args.turbo:
        print()
        print("=" * 70)
        print("turbo (sergeyzh/rubert-tiny-turbo) + структура")
        print("=" * 70)

        backend_turbo = TurboBackend().fit(df["text"].tolist())

        evaluate(pairs, DuplicateRanker(backend_turbo, use_structure=False),
                 "turbo, только косинус")
        res_turbo = evaluate(pairs, DuplicateRanker(backend_turbo, use_structure=True),
                             "turbo + структурные признаки")

        high_t = max(res_turbo["link_thr"], HIGH_FLOOR)
        low_t  = max(0.0, high_t - LOW_GAP)
        print(f"\nturbo авто-пороги: HIGH={high_t:.2f} (LINK), LOW={low_t:.2f} (ASK)")
        demo(backend_turbo, "turbo", high_t, low_t)
        return

    # TF-IDF
    print()
    print("=" * 70)
    print("TF-IDF + структура")
    print("=" * 70)

    backend_tfidf = TfidfBackend().fit(df["text"].tolist())

    evaluate(pairs, DuplicateRanker(backend_tfidf, use_structure=False),
             "TF-IDF, только косинус")
    res_tfidf = evaluate(pairs, DuplicateRanker(backend_tfidf, use_structure=True),
                         "TF-IDF + структурные признаки")

    HIGH = res_tfidf["link_thr"]
    LOW  = max(0.0, HIGH - LOW_GAP)
    print(f"\nTF-IDF авто-пороги: HIGH={HIGH:.2f} (LINK), LOW={LOW:.2f} (ASK)")
    demo(backend_tfidf, "TF-IDF", HIGH, LOW)

if __name__ == "__main__":
    main()