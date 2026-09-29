# AI/ML evaluation (29 September 2026)

The operational pipeline is deliberately hybrid: deterministic intent/actionability
and zone/asset guards, plus a learned character TF-IDF + logistic-regression
category model and semantic score. No generative model changes a domain state.
The optional OpenRouter assistant is a separate, manually invoked help chat;
complaint and group-chat text is never sent to it.

Run `uv run --no-project --python 3.12 --with scikit-learn==1.9.1 python ml/train_runtime.py`.
This writes `models/category_char_lr.json` (data-only; the API loads no pickle)
and `reports/category_eval.json`. The API image includes the artifact.

| Metric | Result | Scope |
|---|---:|---|
| Category accuracy | 0.9286 | 70 held-out messages |
| Category macro-F1 | 0.9317 | 7 categories |
| Chat leakage | 0 overlapping chats | 56 train, 14 test chats |
| Intent accuracy | 1.00 | 30 synthetic regression utterances, not held-out real traffic |
| Category extraction accuracy | 1.00 | labeled subset of those 30 utterances |
| Structured schema validity | 1.00 | all regression calls validate with Pydantic |
| Critical issue E2E | 20 / 20 | clean deterministic repeated runs |

`dataset.csv` contains 350 curated/synthetic issue messages. It contains only
`intent=issue`, so it **cannot support a meaningful learned intent benchmark**.
The older `ml/train_baseline.py` explicitly skips one-class targets; its joblib
outputs are exploratory and not loaded by the API. The runnable runtime artifact
is produced by `ml/train_runtime.py`.

The held-out category result is useful for regression, **not a claim of real
resident-chat quality**. Low-confidence and unknown cases stay manual.
Duplicate matching also requires the same house, zone/asset and category;
semantic similarity is only one small score term. There is not yet a
human-reviewed pairwise duplicate benchmark, real-chat asset-resolution
accuracy, or human correction rate.

Before production rollout, collect consented, anonymized multi-house messages,
label intent/category/location/duplicate pairs, and re-evaluate on wholly
unseen houses and chats. Keep the manual branches until measurements justify
changing thresholds.
