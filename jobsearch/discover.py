"""Fill in the `ats` and `slug` columns of companies.csv.

Two ways, both checked against the live board before anything is written:
  1. Guess slugs from the company name (e.g. "Jane Street" -> janestreet, jane-street)
     and keep a guess only if Greenhouse, Lever or Ashby actually returns a job board.
  2. If `careers_url` is filled in, read that page and look for a Greenhouse, Lever,
     Ashby or Workday link in it.

Companies still blank afterwards (custom career sites) are listed for a Playwright lookup.

Usage: python3 discover.py [--limit N]
"""
from __future__ import annotations

import argparse
import csv
import re
import urllib.request
from pathlib import Path

from fetch import UA, http_json

HERE = Path(__file__).resolve().parent
STOP = {"inc", "llc", "corporation", "corp", "company", "co", "group", "the", "usa", "us", "international", "holdings"}


def candidates(name: str) -> list[str]:
    base = re.sub(r"\(.*?\)", "", name).lower().replace("&", "and")
    words = [w for w in re.findall(r"[a-z0-9]+", base) if w not in STOP]
    # Full name only: a first-word guess ("general") could match some other company's board.
    out = ["".join(words), "-".join(words)]
    return list(dict.fromkeys(c for c in out if c))


PROBES = {
    "greenhouse": lambda s: http_json(f"https://boards-api.greenhouse.io/v1/boards/{s}/jobs").get("jobs") is not None,
    "lever": lambda s: isinstance(http_json(f"https://api.lever.co/v0/postings/{s}?mode=json&limit=1"), list),
    "ashby": lambda s: http_json(f"https://api.ashbyhq.com/posting-api/job-board/{s}").get("jobs") is not None,
}

PAGE_PATTERNS = [
    ("workday", re.compile(r"https?://([a-z0-9-]+\.wd\d+\.myworkdayjobs\.com)/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9_-]+)")),
    ("greenhouse", re.compile(r"(?:boards|job-boards)\.greenhouse\.io/(?:embed/job_board\?for=)?([a-z0-9_-]+)")),
    ("lever", re.compile(r"jobs\.lever\.co/([a-z0-9_-]+)")),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([A-Za-z0-9_.-]+)")),
]


def from_page(url: str):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    page = urllib.request.urlopen(req, timeout=30).read().decode("utf-8", "replace")
    for ats, rx in PAGE_PATTERNS:
        m = rx.search(page)
        if m:
            if ats == "workday":
                host, site = m.group(1), m.group(2)
                return ats, f"{host}/{host.split('.')[0]}/{site}"
            return ats, m.group(1)
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    path = HERE / "companies.csv"
    rows = list(csv.DictReader(open(path, newline="")))
    todo = [r for r in rows if not r["ats"] and r.get("keep", "yes") != "no"]
    if a.limit:
        todo = todo[: a.limit]
    found = 0
    for r in todo:
        hit = None
        if r.get("careers_url"):
            try:
                hit = from_page(r["careers_url"])
            except Exception:
                pass
        for slug in ([] if hit else candidates(r["name"])):
            for ats, probe in PROBES.items():
                try:
                    if probe(slug):
                        hit = (ats, slug)
                        break
                except Exception:
                    continue
            if hit:
                break
        if hit:
            r["ats"], r["slug"] = hit
            r["notes"] = (r.get("notes") or "") + " board found by name guess; check it is the right company" if not r.get("careers_url") else r.get("notes", "")
            found += 1
            print(f"  {r['name']:<45} {hit[0]:<10} {hit[1]}")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    left = [r["name"] for r in rows if not r["ats"] and r.get("keep", "yes") != "no"]
    print(f"\nmapped {found}; {len(left)} still need a Playwright lookup of their careers page")


if __name__ == "__main__":
    main()
