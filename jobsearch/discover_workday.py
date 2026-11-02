"""Find Workday job boards for companies still unmapped in companies.csv.

A Workday tenant's robots.txt lists its public career sites, and a non-existent tenant
returns nothing. So for each company we try likely tenant names across Workday's data
centres (wd1, wd3, wd5, ...), read the site list, then confirm the board answers a job
search before saving it. Matches from a short-name guess are marked for a check.

Usage: python3 discover_workday.py
"""
from __future__ import annotations

import csv
import re
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fetch import UA, http_json

HERE = Path(__file__).resolve().parent
DCS = ["wd1", "wd3", "wd5", "wd12", "wd10", "wd103", "wd108", "wd501", "wd503", "wd101", "wd100"]
STOP = {"inc", "llc", "corporation", "corp", "company", "co", "group", "the", "usa", "us", "international",
        "holdings", "of", "and", "services", "systems", "technologies", "industries", "solutions"}


def tenants(name: str) -> list[tuple[str, bool]]:
    """(tenant guess, is_full_name)."""
    base = re.sub(r"\(.*?\)", "", name).lower().replace("&", " ")
    allw = re.findall(r"[a-z0-9]+", base)
    core = [w for w in allw if w not in STOP] or allw
    out = [("".join(allw), True), ("".join(core), True)]
    if len(core) > 1 and len(core[0]) >= 4:
        out.append((core[0], False))
    initials = "".join(w[0] for w in allw if w not in {"of", "and", "the"})
    if len(initials) >= 3:
        out.append((initials, False))
    seen, res = set(), []
    for t, full in out:
        if t and t not in seen:
            seen.add(t); res.append((t, full))
    return res


def sites(host: str) -> list[str]:
    try:
        req = urllib.request.Request(f"https://{host}/robots.txt", headers={"User-Agent": UA})
        txt = urllib.request.urlopen(req, timeout=15).read().decode("utf-8", "replace")
    except Exception:
        return []
    return re.findall(r"myworkdayjobs\.com/([A-Za-z0-9_-]+)/siteMap\.xml", txt)


# Tenant guesses that were checked and belong to a different organization.
WRONG = {
    "Huntington Ingalls Industries": {"huntington"},   # Huntington Bank
    "SRC Inc": {"src"},                                 # Scottish Rite for Children
    "Life Support International": {"lsi"},              # Arxada
}


def total(host, tenant, site):
    try:
        return http_json(f"https://{host}/wday/cxs/{tenant}/{site}/jobs",
                         {"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""}).get("total") or 0
    except Exception:
        return -1


def probe(name: str):
    for tenant, full in tenants(name):
        if tenant in WRONG.get(name, ()):
            continue
        for dc in DCS:
            host = f"{tenant}.{dc}.myworkdayjobs.com"
            found = sites(host)
            if not found:
                continue
            # Tenants often have side sites (recall, internships, one country); keep the biggest board.
            counts = {s: total(host, tenant, s) for s in found[:12]}
            site = max(counts, key=counts.get)
            if counts[site] < 0:
                continue
            return name, f"{host}/{tenant}/{site}", full, counts[site], found
    return name, None, None, None, None


def main():
    path = HERE / "companies.csv"
    rows = list(csv.DictReader(open(path, newline="")))
    todo = [r["name"] for r in rows if not r["ats"] and r.get("keep", "yes") != "no"]
    with ThreadPoolExecutor(12) as ex:
        results = {n: (slug, full, total, found) for n, slug, full, total, found in ex.map(probe, todo)}
    hits = 0
    for r in rows:
        slug, full, total, found = results.get(r["name"], (None,) * 4)
        if slug:
            hits += 1
            r["ats"], r["slug"] = "workday", slug
            note = "workday board found" + ("" if full else " from a short-name guess; check it is the right company")
            r["notes"] = note
            print(f"  {r['name']:<42} {slug:<70} {total} jobs{'' if full else '  (check)'}")
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)
    left = [r["name"] for r in rows if not r["ats"] and r.get("keep", "yes") != "no"]
    print(f"\nmapped {hits} more; {len(left)} still unmapped")


if __name__ == "__main__":
    main()
