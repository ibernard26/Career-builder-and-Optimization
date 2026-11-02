"""Pull this week's postings from company career boards into one normalized file.

Sources (no browser needed, each board publishes its jobs as JSON):
  greenhouse  slug              boards-api.greenhouse.io
  lever       slug              api.lever.co
  ashby       slug              api.ashbyhq.com
  workday     host/tenant/site  e.g. acme.wd1.myworkdayjobs.com/acme/External
  usajobs     (keyword search)  data.usajobs.gov, needs USAJOBS_API_KEY and USAJOBS_EMAIL

Companies whose `ats` is blank in companies.csv are skipped and listed, so they can be
looked up (careers page -> board type) before the next run. Nothing is ever submitted.

Usage: python3 fetch.py [--out ../private/runs/DATE/jobs.jsonl] [--only NAME]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
UA = "Mozilla/5.0 (job-search helper; personal use)"
TIMEOUT = 30


def http_json(url: str, data: dict | None = None, headers: dict | None = None):
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, headers={"User-Agent": UA, "Accept": "application/json", **(headers or {})})
    if body is not None:
        req.add_header("Content-Type", "application/json")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code in (429, 502, 503) and attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            raise
        except urllib.error.URLError:
            if attempt < 2:
                time.sleep(2 ** (attempt + 1))
                continue
            raise


def strip_html(s: str | None) -> str:
    s = html.unescape(s or "")
    s = re.sub(r"<(br|/p|/li|/div|/h\d)[^>]*>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()


def job(company, source, jid, title, location, url, posted, description, remote=False, extra=None):
    return {
        "id": f"{source}:{company}:{jid}",
        "company": company,
        "source": source,
        "title": (title or "").strip(),
        "location": (location or "").strip(),
        "remote": bool(remote) or "remote" in (location or "").lower(),
        "url": url,
        "posted": posted,  # ISO date or None when the board doesn't say
        "description": description or "",
        **(extra or {}),
    }


def iso(ts) -> str | None:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        return dt.datetime.fromtimestamp(ts / 1000, dt.timezone.utc).date().isoformat()
    try:
        return dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        return None


# ---- adapters -------------------------------------------------------------

def greenhouse(company, slug, **_):
    d = http_json(f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true")
    for j in d.get("jobs", []):
        yield job(company, "greenhouse", j["id"], j.get("title"), (j.get("location") or {}).get("name"),
                  j.get("absolute_url"), iso(j.get("first_published") or j.get("updated_at")), strip_html(j.get("content")))


def lever(company, slug, **_):
    for j in http_json(f"https://api.lever.co/v0/postings/{slug}?mode=json"):
        cats = j.get("categories") or {}
        lists = "\n".join(f"{l.get('text')}\n{strip_html(l.get('content'))}" for l in j.get("lists") or [])
        yield job(company, "lever", j["id"], j.get("text"), cats.get("location"), j.get("hostedUrl"),
                  iso(j.get("createdAt")), f"{j.get('descriptionPlain') or ''}\n{lists}",
                  remote=(j.get("workplaceType") == "remote"))


def ashby(company, slug, **_):
    d = http_json(f"https://api.ashbyhq.com/posting-api/job-board/{slug}?includeCompensation=true")
    for j in d.get("jobs", []):
        yield job(company, "ashby", j.get("id") or j.get("jobUrl"), j.get("title"), j.get("location"), j.get("jobUrl"),
                  iso(j.get("publishedAt")), j.get("descriptionPlain") or strip_html(j.get("descriptionHtml")),
                  remote=j.get("isRemote"))


def _workday_posted(text: str | None, today: dt.date) -> str | None:
    t = (text or "").lower()
    if "today" in t:
        return today.isoformat()
    if "yesterday" in t:
        return (today - dt.timedelta(days=1)).isoformat()
    m = re.search(r"(\d+)\+?\s*days?", t)
    if m:
        return (today - dt.timedelta(days=int(m.group(1)))).isoformat()
    return None


def workday(company, slug, keywords=(), max_days=7, **_):
    """slug = host/tenant/site, e.g. acme.wd5.myworkdayjobs.com/acme/Careers"""
    host, tenant, site = slug.split("/", 2)
    base = f"https://{host}/wday/cxs/{tenant}/{site}"
    today = dt.date.today()
    seen = set()
    for kw in keywords:
        offset = 0
        while offset < 200:
            d = http_json(f"{base}/jobs", {"appliedFacets": {}, "limit": 20, "offset": offset, "searchText": kw})
            posts = d.get("jobPostings", [])
            for p in posts:
                path = p.get("externalPath")
                if not path or path in seen:
                    continue
                seen.add(path)
                posted = _workday_posted(p.get("postedOn"), today)
                if posted and (today - dt.date.fromisoformat(posted)).days > max_days:
                    continue
                try:
                    info = http_json(f"{base}{path}").get("jobPostingInfo", {})
                except Exception:  # detail page failed; keep the listing
                    info = {}
                yield job(company, "workday", path.rsplit("_", 1)[-1], p.get("title"),
                          info.get("location") or p.get("locationsText"), f"https://{host}/{site}{path}",
                          posted, strip_html(info.get("jobDescription")),
                          remote=("remote" in (info.get("remoteType") or "").lower()))
            if len(posts) < 20:
                break
            offset += 20


def usajobs(keywords=(), max_days=7, **_):
    key, email = os.environ.get("USAJOBS_API_KEY"), os.environ.get("USAJOBS_EMAIL")
    if not (key and email):
        raise RuntimeError("set USAJOBS_API_KEY and USAJOBS_EMAIL (free key: developer.usajobs.gov)")
    hdr = {"Host": "data.usajobs.gov", "User-Agent": email, "Authorization-Key": key}
    seen = set()
    for kw in keywords:
        q = urllib.parse.urlencode({"Keyword": kw, "DatePosted": max_days, "ResultsPerPage": 250})
        d = http_json(f"https://data.usajobs.gov/api/search?{q}", headers=hdr)
        for it in d.get("SearchResult", {}).get("SearchResultItems", []):
            m = it.get("MatchedObjectDescriptor", {})
            jid = m.get("PositionID")
            if jid in seen:
                continue
            seen.add(jid)
            details = (m.get("UserArea") or {}).get("Details") or {}
            grade = "/".join(f"{g.get('Code')}" for g in m.get("JobGrade") or [])
            desc = "\n".join(filter(None, [details.get("JobSummary"), m.get("QualificationSummary"),
                                           "\n".join(details.get("MajorDuties") or [])]))
            yield job(m.get("OrganizationName") or "Federal", "usajobs", jid, m.get("PositionTitle"),
                      m.get("PositionLocationDisplay"), m.get("PositionURI"), iso(m.get("PublicationStartDate")),
                      desc, extra={"grade": f"{grade}-{details.get('LowGrade','')}/{details.get('HighGrade','')}"})


ADAPTERS = {"greenhouse": greenhouse, "lever": lever, "ashby": ashby, "workday": workday}


def search_keywords(cfg) -> list[str]:
    # Short, broad terms for boards that need a search phrase (Workday, USAJOBS).
    return ["logistics", "supply chain", "logistician", "integrated logistics support", "product support",
            "inventory", "quantitative analyst", "derivatives", "equity research"]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "private" / "runs" / dt.date.today().isoformat() / "jobs.jsonl"))
    ap.add_argument("--companies", default=str(HERE / "companies.csv"))
    ap.add_argument("--only", help="fetch one company by name")
    ap.add_argument("--no-usajobs", action="store_true")
    a = ap.parse_args(argv)

    cfg = json.loads((HERE / "config.json").read_text())
    days = cfg["posted_within_days"]
    kws = search_keywords(cfg)
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    rows = [r for r in csv.DictReader(open(a.companies, newline=""))
            if (r.get("keep") or "yes").strip().lower() != "no"]
    if a.only:
        rows = [r for r in rows if r["name"].lower() == a.only.lower()]
    count, failed, unmapped = 0, [], []
    with out.open("w") as f:
        for r in rows:
            ats, slug = (r.get("ats") or "").strip(), (r.get("slug") or "").strip()
            if ats not in ADAPTERS or not slug:
                unmapped.append(r["name"])
                continue
            try:
                n = 0
                for j in ADAPTERS[ats](r["name"], slug, keywords=kws, max_days=days):
                    j["category"] = r.get("category", "")
                    f.write(json.dumps(j) + "\n")
                    n += 1
                count += n
                print(f"  {r['name']:<40} {ats:<10} {n:>4} jobs", file=sys.stderr)
            except Exception as e:  # one bad board must not stop the run
                failed.append(f"{r['name']} ({ats}): {e}")
        if not a.no_usajobs and not a.only:
            try:
                n = 0
                for j in usajobs(keywords=["logistics", "logistician", "supply", "integrated logistics support", "inventory management"], max_days=days):
                    j["category"] = "federal"
                    f.write(json.dumps(j) + "\n")
                    n += 1
                count += n
                print(f"  {'USAJOBS':<40} {'usajobs':<10} {n:>4} jobs", file=sys.stderr)
            except Exception as e:
                failed.append(f"USAJOBS: {e}")

    print(f"\n{count} postings -> {out}", file=sys.stderr)
    if failed:
        print(f"\n{len(failed)} sources failed:\n  " + "\n  ".join(failed), file=sys.stderr)
    if unmapped:
        print(f"\n{len(unmapped)} companies need their board looked up: {', '.join(unmapped)}", file=sys.stderr)


if __name__ == "__main__":
    main()
