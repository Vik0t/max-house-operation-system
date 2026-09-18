# AI evaluation

Current benchmark is deliberately small and synthetic: 30 Russian house-chat utterances in `datasets/house_chat_eval/eval.jsonl`.

| Metric | Result | Scope |
|---|---:|---|
| Intent accuracy | 1.00 | 30 synthetic examples |
| Category extraction accuracy | 1.00 | labeled category subset |
| Structured schema validity | 1.00 | all evaluated calls validated by Pydantic |
| Critical E2E success | 20 / 20 | clean deterministic runs |

These numbers are engineering regression metrics, not evidence of production ML quality. Asset resolution, pairwise cluster F1 and human correction rate require the planned 300–500 anonymized/augmented dataset and real chat review.

The deterministic model is intentional for hackathon reproducibility. The pipeline boundaries allow replacing individual stages with an LLM while preserving Pydantic validation, human confirmation and fallbacks.

