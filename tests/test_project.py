"""Runtime smoke tests, data validation and independently isolated scenarios."""

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from commerce.fixtures import money
from commerce.nlu import PortableNLU, RasaNLU
from commerce.store import Repository
from tools.corpus_io import splits
from .scenarios import CASES, MODEL, run_case


class ProjectTests(unittest.TestCase):
    def test_http_workflows(self):
        for case in CASES:
            with self.subTest(case=case[1]):
                result = run_case(*case)
                self.assertEqual(result["status"], "PASS", result["observed"])

    def test_split(self):
        training, holdout = splits()
        model = PortableNLU(MODEL)
        self.assertEqual((len(training), len(holdout), len(model.classes)), (224, 112, 14))
        self.assertEqual(model.parse("🌧").intent, "out_of_scope")

    def test_money_format_and_coupon_scope(self):
        self.assertEqual(money(12345678), "₹1,23,456.78")
        with TemporaryDirectory() as temp:
            repo = Repository(Path(temp) / "check.db")
            docs = repo.official_passages("trail", date(2026, 11, 15))
            self.assertEqual(len(docs), 8)
            self.assertTrue(all(row["source"].startswith("TRAIL-") for row in docs))
            self.assertEqual(repo.catalogue("trail", "anything", maximum=0), [])

    def test_rasa_url_boundary(self):
        for url in ("http://external.example/model/parse", "http://127.0.0.1:5005/unrelated", "https://127.0.0.1:5005/model/parse"):
            with self.assertRaises(ValueError):
                RasaNLU(url)
