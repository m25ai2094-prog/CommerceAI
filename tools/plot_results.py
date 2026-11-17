"""Render project plots, diagrams and clearly labelled interface illustrations."""

import csv
from collections import Counter
import json
from pathlib import Path
import subprocess

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
import numpy as np


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "figures"
EVIDENCE = ROOT / "evidence"
INK, GREEN, TAN, ACCENT = "#213731", "#356e58", "#b9754d", "#f1bb91"


def save(fig, filename):
    fig.savefig(OUT / filename, dpi=209, bbox_inches="tight", facecolor="white", pad_inches=.10)
    plt.close(fig)


def horizontal(labels, values, title, xlabel, filename, *, limits, fmt, bar_labels=None):
    fig, ax = plt.subplots(figsize=(8.45, max(3.25, .29 * len(labels) + .95)))
    bars = ax.barh(labels, values, color=[GREEN if i % 2 == 0 else "#659379" for i in range(len(labels))])
    ax.invert_yaxis()
    ax.set(xlabel=xlabel, title=title, xlim=limits)
    ax.grid(axis="x", color="#dfe8e0")
    ax.set_axisbelow(True)
    ax.bar_label(bars, labels=bar_labels, fmt=fmt, padding=3, fontsize=8)
    save(fig, filename)


def interface_plate():
    fig, ax = plt.subplots(figsize=(9.8, 5.2))
    ax.set(xlim=(0, 980), ylim=(0, 520)); ax.set_axis_off()

    def block(x, y, w, h, fill, border="none"):
        ax.add_patch(Rectangle((x, y), w, h, facecolor=fill, edgecolor=border))

    def label(x, y, value, size=10, color=INK, weight="normal"):
        ax.text(x, y, value, color=color, fontsize=size, fontweight=weight, va="center")

    block(0, 0, 980, 520, "#f6f4ef")
    block(0, 0, 164, 520, "#18292a")
    label(19, 480, "CommerceAI", 10.5, "white", "bold")
    label(22, 424, "Demo stores", 9, "#c7d8ca", "bold")
    for y, name in [(397, "Nook & Loom"), (367, "Trail & Trek")]:
        block(16, y - 14, 131, 27, "#304842")
        label(27, y, name, 9, "white")
    for i, name in enumerate(["Catalogue", "Orders", "Support", "Staff desk"]):
        label(27, 312 - 32 * i, name, 10, "#e8eee8")
    label(20, 29, "Fictional demo data", 7, "#cedbd2")
    label(189, 482, "Store desk   /   Catalogue", 11, INK, "bold")
    block(187, 334, 470, 120, "#24423c")
    label(205, 423, "Home & workspace", 9, "#dce9dc")
    label(205, 390, "Nook & Loom", 24, "white", "bold")
    block(205, 346, 140, 24, ACCENT)
    label(215, 358, "Track an order", 8, "#3d271a", "bold")
    label(187, 308, "Catalogue", 13, INK, "bold")
    block(187, 259, 470, 28, "#fffefa", "#deded3")
    label(199, 273, "Search by name or SKU", 9, "#53666a")
    for i, (product, price, fill) in enumerate([("Arc Desk Lamp", "₹1,799.00", "#eed6c2"),
                                               ("Dune Desk Mat", "₹799.00", "#e4e5cd"),
                                               ("Loop Cable Set", "₹399.00", "#dce8e3"),
                                               ("Knot Planter", "₹1,299.00", "#e9dbeb")]):
        x, y = 187 + i % 2 * 241, 146 - i // 2 * 113
        block(x, y, 229, 101, "#fffefa", "#deded3")
        block(x, y + 62, 229, 39, fill)
        label(x + 11, y + 44, product, 10, INK, "bold")
        label(x + 11, y + 24, price, 9)
        label(x + 109, y + 24, "Compare", 8, "#40554e")
    block(674, 34, 284, 420, "#fffefa", "#deded3")
    label(690, 430, "Assistant", 13, INK, "bold")
    label(690, 406, "Nook & Loom", 9, "#53666a")
    block(689, 308, 255, 73, "#f4f2e8")
    label(701, 357, "Welcome to Nook & Loom.", 9)
    label(701, 337, "Find products, check orders", 8)
    label(701, 321, "or ask a store policy question.", 8)
    for y, choice in [(122, "Track an order"), (97, "Ask about a store policy")]:
        label(692, y, choice, 8, "#3b5e50", "bold")
    block(690, 51, 251, 27, "#f3eee1", "#deded3")
    label(699, 64, "Ask about this store", 9, "#53666a")
    save(fig, "interface_layout.png")


def main():
    data = json.loads((EVIDENCE / "summary.json").read_text(encoding="utf-8"))
    labels = data["classes"]
    short = [f"I{i:02d}" for i in range(1, len(labels) + 1)]
    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 9, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.titleweight": "bold", "text.color": INK})
    matrix = np.array(data["nlu"]["matrix"])
    fig, ax = plt.subplots(figsize=(7.4, 6.1))
    im = ax.imshow(matrix, cmap="YlGn", vmin=0, vmax=8)
    ax.set(xticks=range(len(labels)), xticklabels=short, yticks=range(len(labels)), yticklabels=short,
           title="Held-out intent predictions", xlabel="Predicted intent", ylabel="Expected intent")
    for i, j in np.argwhere(matrix > 0):
        ax.text(j, i, str(matrix[i, j]), ha="center", va="center", color="white" if matrix[i, j] > 4 else INK)
    fig.colorbar(im, ax=ax, shrink=.7, label="Examples")
    save(fig, "nlu_confusion.png")

    per_intent = sorted(data["nlu"]["by_intent"], key=lambda row: (-row["f1"], row["label"]))
    horizontal([r["label"].replace("_", " ") for r in per_intent], [r["f1"] for r in per_intent],
               "F1 by intent", "F1 score", "nlu_intent_f1.png", limits=(0, 1.12), fmt="%.2f")
    horizontal(["Word + character TF-IDF", "Word unigram baseline"],
               [data["nlu"]["accuracy"] * 100, data["baseline"]["accuracy"] * 100],
               "Held-out model comparison", "Accuracy (%)", "nlu_models.png", limits=(0, 110), fmt="%.2f")

    retrieval = data["retrieval"]
    values = np.arange(2)
    fig, ax = plt.subplots(figsize=(7.8, 3.75))
    for name, offset, color, label in (("bm25", -.19, GREEN, "BM25 + evidence gate"),
                                       ("overlap", .19, TAN, "Term overlap")):
        r = retrieval[name]
        bars = ax.bar(values + offset, [r["recall_at_one"] * 100, r["correct_abstain"] / retrieval["unanswerable"] * 100],
                      .38, color=color, label=label)
        ax.bar_label(bars, fmt="%.1f%%", padding=3, fontsize=8)
    ax.set(xticks=values, xticklabels=["Correct topic (24 queries)", "Correct abstention (8 queries)"],
           ylim=(0, 124), ylabel="Rate (%)", title="Policy retrieval and abstention")
    ax.legend(frameon=False, loc="upper center", ncol=2)
    save(fig, "policy_comparison.png")

    checks = data["workflows"]["cases"]
    groups = Counter(c["group"] for c in checks)
    counts = Counter(c["group"] for c in checks if c["status"] == "PASS")
    names = sorted(groups)
    horizontal(names, [counts[name] for name in names], "Local workflow acceptance", "Passed scenarios", "workflow_cases.png",
               limits=(0, max(groups.values()) + 2), fmt="%d", bar_labels=[f"{counts[n]}/{groups[n]}" for n in names])

    with (EVIDENCE / "http_timings.csv").open(encoding="utf-8") as source:
        turns = [float(row["ms"]) for row in csv.DictReader(source)]
    with (EVIDENCE / "nlu_predictions.csv").open(encoding="utf-8") as source:
        intents = [float(row["ms"]) for row in csv.DictReader(source)]
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.45))
    for ax, values, title in zip(axes, (intents, turns), ("Warm classifier", "Local HTTP chat")):
        v = sorted(values)
        ax.step(v, np.arange(1, len(v) + 1) / len(v) * 100, where="post", color=GREEN, linewidth=2)
        ax.axhline(95, color=TAN, linestyle="--", linewidth=1)
        ax.set(title=f"{title} (n={len(v)})", xlabel="Latency (ms)", ylim=(0, 104))
        ax.grid(color="#e1e8e0")
    axes[0].set_ylabel("Cumulative share (%)")
    fig.tight_layout()
    save(fig, "latency.png")

    cases = json.loads((EVIDENCE / "workflow_traces.json").read_text(encoding="utf-8"))
    use = next(c for c in cases if c["name"] == "Replacement intake and status")
    receipt = next(reply for reply in use["transcript"] if reply["event"] == "confirmed")
    fig, ax = plt.subplots(figsize=(8.6, 3.1))
    ax.set_axis_off(); ax.add_patch(Rectangle((0, 0), 1, 1, transform=ax.transAxes, color="#234137"))
    ax.text(.045, .89, "Recorded replacement response", transform=ax.transAxes, color="#f8c3a0", weight="bold", size=13)
    lines = [f"event      {receipt['event']}", f"reference  {receipt['reference']}",
             *[f"{key.lower():<10} {value}" for key, value in receipt["rows"]],
             f"policy     {receipt['citation']['source']}  v{receipt['citation']['version']}"]
    ax.text(.045, .765, "\n".join(lines), color="white", transform=ax.transAxes, va="top", family="monospace", size=10)
    save(fig, "replacement_response.png")
    interface_plate()
    for name in ("architecture", "review", "schema"):
        subprocess.run(["dot", "-Tpng", str(OUT / f"{name}.dot"), "-o", str(OUT / f"{name}.png")], check=True)
    print("Generated eleven CommerceAI figures.")


if __name__ == "__main__":
    main()
