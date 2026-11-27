"""Intent-classification accuracy of the default rule-based classifier on eval/classification_set.json.
The set was written by the project author (not independent). The LLM classifier is NOT evaluated (no API key)."""

import json
import os
import sys
from collections import Counter

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)
from support.classify import INTENTS, rule_classify, llm_classify
import time

T0 = time.time()
rows = json.load(open(f"{root}/eval/classification_set.json"))
conf = Counter()
wrong = []
for r in rows:
    if os.getenv("EVAL_LLM"):
        cp = "/tmp/sup_cache.json"
        cache = json.load(open(cp)) if os.path.exists(cp) else {}
        if r["text"] not in cache:
            if time.time() - T0 > 95:
                sys.exit("partial; rerun to continue")
            cache[r["text"]] = llm_classify(r["text"])
            json.dump(cache, open(cp, "w"))
            time.sleep(4.2)
        p = cache[r["text"]]
    else:
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
    "classifier": "gemini" if os.getenv("EVAL_LLM") else "rules",
}
json.dump(res, open(f"{root}/eval/results{'_gemini' if os.getenv('EVAL_LLM') else ''}.json", "w"), indent=1)
print(json.dumps({k: v for k, v in res.items() if k != "errors"}, indent=1))
print("errors:", json.dumps(wrong, indent=1))
