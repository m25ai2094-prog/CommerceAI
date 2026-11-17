"""Portable sparse classifier and optional Rasa HTTP parse adapter."""

from collections import Counter
from dataclasses import dataclass
import json
from math import exp, sqrt
from pathlib import Path
import re
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .fixtures import INTENTS


TOKEN = re.compile(r"[a-z0-9]+")


def tokens(text):
    return TOKEN.findall(text.casefold())



@dataclass(frozen=True)
class Prediction:
    intent: str
    confidence: float
    margin: float


class PortableNLU:
    name = "Portable TF-IDF + logistic regression"

    def __init__(self, path: Path):
        self.model = json.loads(Path(path).read_text(encoding="utf-8"))
        self.classes = self.model["classes"]
        if set(self.classes) != INTENTS:
            raise ValueError("The bundled model and project intent taxonomy disagree.")

    def parse(self, text):
        words = tokens(text)
        word_terms = words + [a + " " + b for a, b in zip(words, words[1:])]
        char_terms = []
        for word in words:
            padded = " " + word + " "
            for size in range(3, min(5, len(padded)) + 1):
                char_terms.extend(padded[i:i + size] for i in range(len(padded) - size + 1))
        scores = self.model["bias"].copy()
        found = False
        weights = self.model["weights"]
        for terms, vocabulary in zip((word_terms, char_terms), self.model["vocabularies"]):
            active = [(vocabulary[term][0], count * vocabulary[term][1])
                      for term, count in Counter(terms).items() if term in vocabulary]
            if active:
                found = True
                norm = sqrt(sum(value * value for _, value in active))
                for label in range(len(scores)):
                    scores[label] += sum(weights[label][i] * value / norm for i, value in active)
        if not found:
            return Prediction("out_of_scope", 0, 0)
        maximum = max(scores)
        values = [exp(value - maximum) for value in scores]
        total = sum(values)
        first, second = sorted(range(len(scores)), key=values.__getitem__, reverse=True)[:2]
        confidence = values[first] / total
        margin = confidence - values[second] / total
        accepted = confidence >= self.model["minimum"] and margin >= self.model["ambiguity"]
        return Prediction(self.classes[first] if accepted else "out_of_scope", confidence, margin)


class NLUUnavailable(RuntimeError):
    """A configured Rasa service is unreachable or returned an invalid result."""


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class RasaNLU:
    name = "Rasa NLU over /model/parse"

    def __init__(self, endpoint):
        url = urlsplit(endpoint)
        if (url.scheme != "http" or url.hostname != "127.0.0.1" or url.port is None
                or url.path != "/model/parse" or url.username or url.password
                or url.query or url.fragment):
            raise ValueError("Use a loopback Rasa URL such as http://127.0.0.1:5005/model/parse.")
        self.endpoint = endpoint
        self.opener = build_opener(ProxyHandler({}), NoRedirect)

    def parse(self, text):
        request = Request(self.endpoint, data=json.dumps({"text": text}).encode(),
                          headers={"Content-Type": "application/json"}, method="POST")
        try:
            with self.opener.open(request, timeout=5) as response:
                payload = json.loads(response.read(65536))
            intent = payload["intent"]["name"]
            confidence = float(payload["intent"]["confidence"])
            if not 0 <= confidence <= 1:
                raise ValueError("Confidence outside [0, 1].")
        except (URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
            raise NLUUnavailable("The configured Rasa NLU service did not return a usable prediction.") from exc
        return Prediction(intent if intent in INTENTS else "out_of_scope", confidence, 0)
