"""Intent-classification accuracy of the default rule-based classifier on eval/classification_set.json.
The set was written by the project author (not independent). The LLM classifier is NOT evaluated (no API key)."""

import json
import os
import sys
from collections import Counter

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)
from support.classify import INTENTS, rule_classify

rows = json.load(open(f"{root}/eval/classification_set.json"))
conf = Counter()
wrong = []
for r in rows:
    p = rule_classify(r["text"])
    conf[(r["label"], p)] += 1
    if p != r["label"]:
        wrong.append({"text": r["text"], "label": r["label"], "predicted": p})
acc = 1 - len(wrong) / len(rows)
per = {}
for l in INTENTS:
    tp = conf[(l, l)]
    fp = sum(conf[(x, l)] for x in INTENTS if x != l)
    fn = sum(conf[(l, x)] for x in INTENTS if x != l)
    per[l] = {
        "precision": round(tp / (tp + fp), 3) if tp + fp else None,
        "recall": round(tp / (tp + fn), 3) if tp + fn else None,
        "n": tp + fn,
    }
res = {
    "n": len(rows),
    "accuracy": round(acc, 3),
    "per_intent": per,
    "errors": wrong,
    "classifier": "rules",
}
json.dump(res, open(f"{root}/eval/results.json", "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "errors"}, indent=1))
print("errors:", json.dumps(wrong, indent=1))
