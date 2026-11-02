"""Run: python3 -m unittest discover -s jobsearch/tests
Postings here are made-up test fixtures, not real jobs."""
import datetime as dt
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import score  # noqa: E402
from fetch import _workday_posted  # noqa: E402

CFG = json.loads((Path(score.HERE) / "config.json").read_text())
PROFILE = {
    "experience_years": {"logistics_total": 5},
    "skills": ["inventory control", "cycle count", "sap", "gcss-mc", "excel", "logistics", "sustainment", "dmsms"],
    "skills_in_progress": ["python", "sql"],
    "pay": {"floor_hourly": 50, "floor_annual": 95000},
}
TODAY = dt.date.today().isoformat()


def posting(title, desc, location="Arlington, VA", **kw):
    return {"id": f"t:{title}", "company": "TestCo", "source": "test", "title": title, "location": location,
            "remote": False, "url": "https://example.com", "posted": TODAY, "description": desc, **kw}


class Parsing(unittest.TestCase):
    def test_word_boundaries(self):
        self.assertFalse(score.has("equity derivatives analyst", "iv"))
        self.assertTrue(score.has("logistics analyst iv", "iv"))

    def test_classify(self):
        self.assertEqual(score.classify("ILS Engineer II", CFG), ("apply", "ils_engineer"))
        self.assertEqual(score.classify("Logistician", CFG), ("apply", "logistician"))
        self.assertEqual(score.classify("Quantitative Researcher", CFG)[0], "benchmark")
        self.assertEqual(score.classify("Software Engineer", CFG), (None, None))

    def test_years(self):
        self.assertEqual(score.years_required("Requires 3+ years of logistics experience"), 3)
        self.assertEqual(score.years_required("5-7 years experience, or 3 years with a degree"), 3)
        self.assertIsNone(score.years_required("no requirement"))

    def test_degree(self):
        self.assertEqual(score.degree_required("Bachelor's degree required"), "bachelors")
        self.assertEqual(score.degree_required("Bachelor's degree or equivalent experience"), "bachelors_or_experience")
        self.assertEqual(score.degree_required("PhD in physics"), "phd")

    def test_pay(self):
        self.assertEqual(score.pay_range("Pay: $45.00 - $55.00 per hour"), (45.0, 55.0, "hour"))
        self.assertEqual(score.pay_range("Salary range $95,000 - $130,000 annually"), (95000.0, 130000.0, "year"))
        self.assertEqual(score.pay_range("$90k-$110k"), (90000.0, 110000.0, "year"))
        self.assertIsNone(score.pay_range("competitive pay"))

    def test_workday_dates(self):
        today = dt.date(2026, 11, 2)
        self.assertEqual(_workday_posted("Posted Today", today), "2026-11-02")
        self.assertEqual(_workday_posted("Posted 3 Days Ago", today), "2026-10-30")
        self.assertEqual(_workday_posted("Posted 30+ Days Ago", today), "2026-10-03")


class Scoring(unittest.TestCase):
    def s(self, job):
        job["family"] = score.classify(job["title"], CFG)[1]
        return score.score_apply(job, CFG, PROFILE)

    def test_good_fit_beats_poor_fit(self):
        good = self.s(posting("Logistician", "3+ years logistics. Inventory control, cycle count, SAP, GCSS-MC. Secret clearance required. $50-$60 per hour"))
        poor = self.s(posting("Logistics Manager", "10+ years. Bachelor's degree required. TS/SCI required.", location="Denver, CO"))
        self.assertGreaterEqual(good[0], 65)
        self.assertLess(poor[0], 40)
        self.assertIn("outside priority areas", poor[3])

    def test_pay_below_floor_flagged(self):
        r = self.s(posting("Supply Chain Analyst", "Excel, SAP. $22 - $28 per hour"))
        self.assertTrue(any("below your" in f for f in r[3]))

    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as d:
            p, prof = Path(d) / "jobs.jsonl", Path(d) / "profile.json"
            prof.write_text(json.dumps(PROFILE))
            jobs = [posting("ILS Engineer", "Provisioning, LSA, GEIA-STD-0007, sustainment, DMSMS. Secret clearance."),
                    posting("Quantitative Analyst", "PhD in mathematics. Python, C++, stochastic calculus. CFA a plus.", location="New York, NY")]
            p.write_text("\n".join(json.dumps(j) for j in jobs))
            score.main(p, prof)
            self.assertIn("ILS Engineer", (Path(d) / "scored.csv").read_text())
            gaps = (Path(d) / "finance_gaps.md").read_text()
            self.assertIn("stochastic calculus", gaps)
            self.assertIn("phd", gaps)


if __name__ == "__main__":
    unittest.main()
