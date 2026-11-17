"""Evaluate the frozen intent split, tenant retrieval, and the local HTTP workflows."""

from argparse import ArgumentParser
from collections import Counter
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import ceil
from pathlib import Path
import platform
import sqlite3
from statistics import mean, median
from tempfile import TemporaryDirectory
from time import perf_counter

from commerce.knowledge import Knowledge
from commerce.nlu import PortableNLU
from commerce.store import Repository
from tests.scenarios import DATE, MODEL, ROOT, run_cases
from tools.corpus_io import splits


def classification(gold, predicted, labels):
    pairs = Counter(zip(gold, predicted))
    by_intent = []
    for label in labels:
        tp = pairs[label, label]
        support = gold.count(label)
        returned = predicted.count(label)
        precision = tp / returned if returned else 0
        recall = tp / support if support else 0
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0
        by_intent.append(dict(label=label, tp=tp, support=support, precision=precision, recall=recall, f1=f1))
    total = len(gold)
    correct = sum(row["tp"] for row in by_intent)
    return dict(correct=correct, total=total, accuracy=correct / total, macro_f1=mean(row["f1"] for row in by_intent),
                by_intent=by_intent, matrix=[[pairs[a, b] for b in labels] for a in labels])


def latency(values):
    ordered = sorted(values)
    return dict(count=len(ordered), median_ms=median(ordered), p95_ms=ordered[ceil(.95 * len(ordered)) - 1],
                mean_ms=mean(ordered), max_ms=ordered[-1])


def retrieval():
    with TemporaryDirectory(prefix="commerce-policy-") as temp:
        service = Knowledge(Repository(Path(temp) / "policy.db", today=lambda: DATE))
        with (ROOT / "corpus" / "policy_queries.tsv").open(encoding="utf-8") as source:
            cases = list(csv.DictReader(source, delimiter="\t"))
        for case in cases:
            beginning = perf_counter()
            found = service.answer(case["tenant"], case["text"])
            case["ms"] = round((perf_counter() - beginning) * 1000, 3)
            case["predicted"] = found["topic"] if found else "ABSTAIN"
            case["citation"] = found["citation"]["source"] if found else ""
            case["version"] = found["citation"]["version"] if found else ""
            case["baseline"] = service.baseline(case["tenant"], case["text"]) or "ABSTAIN"
    applicable = [r for r in cases if r["topic"] != "ABSTAIN"]
    unknown = [r for r in cases if r["topic"] == "ABSTAIN"]
    summary = {"queries": len(cases), "answerable": len(applicable), "unanswerable": len(unknown),
               "latency": latency([r["ms"] for r in cases])}
    for name, field in (("bm25", "predicted"), ("overlap", "baseline")):
        answered = [r for r in cases if r[field] != "ABSTAIN"]
        correct = sum(r[field] == r["topic"] for r in applicable)
        correct_abstain = sum(r[field] == "ABSTAIN" for r in unknown)
        summary[name] = {"correct_topic": correct, "correct_abstain": correct_abstain, "answers": len(answered),
                         "recall_at_one": correct / len(applicable), "selective_precision": correct / len(answered) if answered else 0.,
                         "decision_accuracy": (correct + correct_abstain) / len(cases)}
    return summary, cases


def write_csv(path, records):
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=records[0])
        writer.writeheader()
        writer.writerows(records)


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=ROOT / "evidence")
    output = parser.parse_args().out
    output.mkdir(parents=True, exist_ok=True)
    _, holdout = splits()
    model = PortableNLU(MODEL)
    meta = json.loads((ROOT / "models" / "training_metadata.json").read_text(encoding="utf-8"))
    predictions = []
    for (utterance, label), base in zip(holdout, meta.pop("baseline"), strict=True):
        start = perf_counter()
        p = model.parse(utterance)
        elapsed = round((perf_counter() - start) * 1000, 4)
        predictions.append(dict(text=utterance, expected=label, predicted=p.intent, confidence=round(p.confidence, 6),
                                margin=round(p.margin, 6), baseline=base, ms=elapsed))
    references = [r["expected"] for r in predictions]
    nlu = classification(references, [r["predicted"] for r in predictions], model.classes)
    baseline = classification(references, [r["baseline"] for r in predictions], model.classes)
    knowledge, queries = retrieval()
    cases = run_cases()
    turns = [{"scenario": c["name"], "group": c["group"], **turn} for c in cases for turn in c["timings"]]
    passed = sum(c["status"] == "PASS" for c in cases)
    report = {"run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "fixture_date": DATE.isoformat(),
              "python": platform.python_version(), "machine": platform.machine(), "system": platform.system(),
              "sqlite": sqlite3.sqlite_version, "model_sha256": sha256(MODEL.read_bytes()).hexdigest(),
              "classes": model.classes, "training": meta, "nlu": nlu, "baseline": baseline,
              "retrieval": knowledge, "http_latency": latency([r["ms"] for r in turns]),
              "nlu_latency": latency([r["ms"] for r in predictions]),
              "workflows": {"passed": passed, "total": len(cases),
                            "cases": [{k: c[k] for k in ("group", "name", "status", "observed")} for c in cases]}}
    for name, data in (("summary.json", report), ("workflow_traces.json", cases)):
        (output / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for name, rows in (("nlu_predictions.csv", predictions), ("per_intent.csv", nlu["by_intent"]),
                       ("policy_predictions.csv", queries), ("http_timings.csv", turns)):
        write_csv(output / name, rows)
    for case in cases:
        print(f"{case['status']} [{case['group']}] {case['name']} — {case['observed']}")
    print(f"Workflows {passed}/{len(cases)}. NLU {nlu['correct']}/{nlu['total']} ({nlu['accuracy']:.2%}), macro F1 {nlu['macro_f1']:.4f}.")
    print(f"Word-only baseline {baseline['accuracy']:.2%}, macro F1 {baseline['macro_f1']:.4f}.")
    q = knowledge["bm25"]
    print(f"Cited topics {q['correct_topic']}/{knowledge['answerable']}. Correct abstentions {q['correct_abstain']}/{knowledge['unanswerable']}.")
    print(f"Measured {len(turns)} loopback chat turns.")
    if passed != len(cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
