"""Approved, current, tenant-filtered BM25 retrieval with cited answers."""

from collections import Counter
from math import log
import re


STOP = set("a an and any are as at be by can could did do does for from had has have how i in is it me my of on or our please should so that the their them there these they this to was we were what when where which who will with would you your about store stores policy policies many much tell want need know".split())
ALIASES = {"returns": "return", "returning": "return", "shipping": "shipping", "ship": "shipping", "ships": "shipping",
           "postage": "shipping", "refunds": "refund", "refunded": "refund", "warranties": "warranty", "guarantee": "warranty",
           "exchange": "replacement", "replacements": "replacement", "reimbursements": "refund", "reimbursement": "refund",
           "cancellation": "cancel", "cancelled": "cancel", "cancelling": "cancel", "charges": "charge", "fees": "charge",
           "business": "business", "hours": "hours", "days": "days", "long": "duration"}


def terms(text):
    tokens = re.findall(r"[a-z0-9]+", text.casefold())
    return [ALIASES.get(token, token) for token in tokens if token not in STOP and len(token) > 1]


class Knowledge:
    def __init__(self, repository):
        self.repo = repository

    def rank(self, tenant, question):
        words = set(terms(question))
        documents = self.repo.official_passages(tenant)
        counts = [Counter(terms(doc["keywords"] + " " + doc["passage"])) for doc in documents]
        length = [sum(count.values()) for count in counts]
        average = sum(length) / len(length) if length else 1
        frequencies = {word: sum(word in count for count in counts) for word in words}
        matches = []
        for doc, count, size in zip(documents, counts, length):
            overlap = words & count.keys()
            if not overlap:
                continue
            score = sum(log(1 + (len(documents) - frequencies[word] + .5) / (frequencies[word] + .5)) *
                        (count[word] * 2.2) / (count[word] + 1.2 * (.25 + .75 * size / average))
                        for word in sorted(overlap))
            matches.append((score, len(overlap), doc))
        return sorted(matches, key=lambda hit: (-hit[0], -hit[1], hit[2]["source"], hit[2]["version"]))

    def answer(self, tenant, question):
        hits = self.rank(tenant, question)
        if not hits:
            return None
        score, overlap, doc = hits[0]
        if overlap < 2 or score < 1.3:
            return None
        if any(other["topic"] == doc["topic"] and other["passage"] != doc["passage"]
               for _, _, other in hits[1:]):
            return None
        if len(hits) > 1 and hits[1][0] > .92 * score:
            return None
        return {"passage": doc["passage"], "citation": self.repo.cite(doc), "score": round(score, 4), "topic": doc["topic"]}

    def baseline(self, tenant, question):
        query = set(terms(question))
        docs = self.repo.official_passages(tenant)
        hits = [(len(query & set(terms(doc["keywords"] + " " + doc["passage"]))), doc) for doc in docs]
        hits.sort(key=lambda h: (-h[0], h[1]["source"]))
        return hits[0][1]["topic"] if hits and hits[0][0] > 0 else None
