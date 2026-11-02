"""Build an application packet for the jobs you picked.

Reads a run's scored.csv and private/profile.json, and writes
private/runs/DATE/packet/ with:
  packet.md    one section per job: link, your standard answers, and a slot for each
               drafted answer (filled in by Claude after reading the posting)
  tracker.csv  one row per job; you mark `submitted` after pressing Submit yourself
  resume.pdf   copied from private/

Usage: python3 packet.py ../private/runs/DATE/scored.csv ID [ID ...]
       python3 packet.py ../private/runs/DATE/scored.csv --strong
"""
from __future__ import annotations

import csv
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent


def main(argv):
    scored = Path(argv[0])
    rows = list(csv.DictReader(scored.open(newline="")))
    if argv[1:] == ["--strong"]:
        picked = [r for r in rows if r["strong"] == "yes"]
    else:
        ids = set(argv[1:])
        picked = [r for r in rows if r["id"] in ids]
    prof = json.loads((ROOT / "private" / "profile.json").read_text())
    std = prof.get("application_answers", {})

    out = scored.parent / "packet"
    out.mkdir(exist_ok=True)
    shutil.copy(ROOT / "private" / "resume.pdf", out / "resume.pdf")

    lines = ["# Application packet", "",
             "Fill each form from its section. Leave anything marked NEEDS YOU blank and list it.",
             "Never press Submit: the applicant does that.", "",
             "## Standard answers (same for every application)"]
    for k, v in std.items():
        lines.append(f"- **{k}:** {v if v not in (None, '') else 'NEEDS YOU'}")
    for i, r in enumerate(picked, 1):
        lines += ["", f"## {i}. {r['title']}, {r['company']}",
                  f"- Link: {r['url']}", f"- Location: {r['location']}", f"- Score: {r['score']}",
                  f"- Gaps to be ready for: {r['gaps'] or 'none flagged'}", "",
                  "### Why this company / why this role", "DRAFT PENDING", "",
                  "### Other questions on the form", "DRAFT PENDING (filled after reading the live form)"]
    (out / "packet.md").write_text("\n".join(lines) + "\n")

    with (out / "tracker.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id", "company", "title", "url", "status", "submitted_on", "notes"])
        for r in picked:
            w.writerow([r["id"], r["company"], r["title"], r["url"], "drafted", "", ""])
    print(f"{len(picked)} jobs -> {out}")


if __name__ == "__main__":
    main(sys.argv[1:])
