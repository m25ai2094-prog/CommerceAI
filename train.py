"""Train and export the portable classifier. Requires requirements-training.txt."""

import json

import numpy as np
from scipy.sparse import hstack
import sklearn
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.model_selection import StratifiedKFold

from commerce.nlu import tokens
from tools.corpus_io import ROOT, splits


def vectors():
    return [TfidfVectorizer(ngram_range=(1, 2), token_pattern=r"[a-z0-9]+", lowercase=False),
            TfidfVectorizer(ngram_range=(3, 5), analyzer="char_wb", lowercase=False, min_df=2)]


def transform(components, text, fit=False):
    return hstack([component.fit_transform(text) if fit else component.transform(text)
                   for component in components], format="csr")


def predict(probs, classes, cutoff, ambiguity):
    order = np.argsort(probs, axis=1)
    rows = np.arange(len(order))
    top, second = probs[rows, order[:, -1]], probs[rows, order[:, -2]]
    return np.where((top >= cutoff) & ((top - second) >= ambiguity),
                    classes[order[:, -1]], "out_of_scope")


def main():
    training, heldout = splits()
    texts, labels = map(np.array, zip(*[(" ".join(tokens(s)), y) for s, y in training]))
    classes = np.unique(labels)
    penalties = (3, 10, 30, 100)
    cv = {p: np.zeros((len(texts), len(classes))) for p in penalties}
    splitter = StratifiedKFold(n_splits=4, shuffle=True, random_state=42)
    for train, valid in splitter.split(texts, labels):
        encoder = vectors()
        x = transform(encoder, texts[train], fit=True)
        v = transform(encoder, texts[valid])
        for penalty in penalties:
            model = LogisticRegression(C=penalty, max_iter=800).fit(x, labels[train])
            cv[penalty][valid] = model.predict_proba(v)
    candidates = []
    for penalty, probabilities in cv.items():
        for cutoff in (.14, .20, .26, .32):
            for gap in (.01, .03, .06):
                predicted = predict(probabilities, classes, cutoff, gap)
                candidates.append((f1_score(labels, predicted, average="macro"), -penalty, -cutoff, -gap))
    validation, penalty, cutoff, ambiguity = max(candidates)
    penalty, cutoff, ambiguity = -penalty, -cutoff, -ambiguity
    encoder = vectors()
    model = LogisticRegression(C=penalty, max_iter=800).fit(transform(encoder, texts, fit=True), labels)
    vocabularies, offset = [], 0
    for part in encoder:
        vocabularies.append({term: [offset + i, round(float(part.idf_[i]), 8)]
                             for term, i in part.vocabulary_.items()})
        offset += len(part.vocabulary_)
    payload = {"classes": model.classes_.tolist(), "weights": np.round(model.coef_, 8).tolist(),
               "bias": np.round(model.intercept_, 8).tolist(), "vocabularies": vocabularies,
               "minimum": cutoff, "ambiguity": ambiguity}
    (ROOT / "models" / "commerce_intents.json").write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    base = TfidfVectorizer(token_pattern=r"[a-z0-9]+", lowercase=False)
    basic = LogisticRegression(C=10, max_iter=800).fit(base.fit_transform(texts), labels)
    test_text = [" ".join(tokens(s)) for s, _ in heldout]
    base_predictions = basic.predict(base.transform(test_text)).tolist()
    report = {"train": len(training), "heldout": len(heldout), "features": offset,
              "word_features": len(vocabularies[0]), "char_features": len(vocabularies[1]),
              "folds": 4, "seed": 42, "training_cv_macro_f1": validation,
              "C": penalty, "minimum": cutoff, "ambiguity": ambiguity,
              "sklearn": sklearn.__version__, "baseline": base_predictions}
    (ROOT / "models" / "training_metadata.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    groups = {name: [] for name in classes}
    for text, name in training:
        groups[name].append(text)
    lines = ['version: "3.1"', "", "nlu:"]
    for name, examples in groups.items():
        lines += [f"- intent: {name}", "  examples: |", *[f"    - {text}" for text in examples]]
    (ROOT / "rasa" / "data" / "nlu.yml").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Exported {len(training)} training examples, {len(heldout)} holdout examples, {offset} features.")
    print(f"Training CV macro F1 {validation:.4f}, C={penalty}, floor={cutoff}, margin={ambiguity}.")


if __name__ == "__main__":
    main()
