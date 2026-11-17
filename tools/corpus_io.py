"""Read the versioned training and evaluation splits."""

from pathlib import Path

from commerce.fixtures import INTENTS
from commerce.nlu import tokens

ROOT = Path(__file__).resolve().parents[1]


def read_split(name):
    rows = []
    for line in (ROOT / "corpus" / (name + ".txt")).read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#"):
            label, examples = line.split("\t", 1)
            rows.extend((text.strip(), label) for text in examples.split("|"))
    if {label for _, label in rows} != INTENTS:
        raise ValueError(f"{name} has an incomplete intent taxonomy.")
    normal = {" ".join(tokens(text)) for text, _ in rows}
    if len(normal) != len(rows):
        raise ValueError(f"{name} contains duplicate normalized text.")
    return rows


def splits():
    train, test = read_split("train"), read_split("heldout")
    assert not {" ".join(tokens(s)) for s, _ in train} & {" ".join(tokens(s)) for s, _ in test}
    return train, test
