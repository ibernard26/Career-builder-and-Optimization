"""Score fetched postings against private/profile.json.

Two tracks, decided by job title:
  apply      SCM / ILS / logistics roles -> 0-100 fit score, reasons and gaps, ranked list
  benchmark  quant / hedge fund / equity & derivatives -> never scored for applying; their
             requirements are tallied into a gap report (degrees, skills, certifications)

The score is a first-pass filter. Strong matches still get a human (and Claude) read
before anything is drafted.

Usage: python3 score.py ../private/runs/DATE/jobs.jsonl
Writes next to the input: scored.csv, matches.md, finance_gaps.md
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
HOURS_PER_YEAR = 2080


def has(text: str, term: str) -> bool:
    """Whole-word, case-insensitive match (so 'iv' doesn't hit 'derivatives')."""
    return re.search(r"(?<![a-z0-9])" + re.escape(term.lower()) + r"(?![a-z0-9])", text) is not None


def any_of(text: str, terms) -> list[str]:
    return [t for t in terms if has(text, t)]


def classify(title: str, cfg) -> tuple[str | None, str | None]:
    t = title.lower()
    for track in ("apply", "benchmark"):
        for fam, words in cfg["tracks"][track]["families"].items():
            if any_of(t, words):
                return track, fam
    return None, None


# ---- requirement parsing --------------------------------------------------

YEARS_RE = re.compile(r"(\d{1,2})\s*(?:\+|or more)?\s*(?:-|to)?\s*(?:\d{1,2}\s*)?\+?\s*years?", re.I)


def years_required(text: str) -> int | None:
    vals = [int(m.group(1)) for m in YEARS_RE.finditer(text) if 0 < int(m.group(1)) <= 25]
    return min(vals) if vals else None  # the lowest stated bar is usually the minimum


DEGREE_PATTERNS = [  # lowest first
    ("associates", r"associate'?s degree|associate degree"),
    ("bachelors", r"bachelor'?s|\bb\.s\.|\bb\.a\.|\bbs\b|\bba\b|undergraduate degree|4-year degree|four-year degree"),
    ("masters", r"master'?s|\bm\.s\.|\bms\b|\bmba\b|\bmfe\b"),
    ("phd", r"ph\.?d|doctorate"),
]


def degree_mentions(text: str) -> list[tuple[str, bool]]:
    """Every degree level named, with whether its sentence calls it preferred / optional."""
    out = []
    for sent in re.split(r"(?<=[.;\n])\s+", text.lower()):
        soft = re.search(r"preferred|a plus|desired|nice to have|or equivalent|in lieu|equivalent combination", sent) is not None
        for level, rx in DEGREE_PATTERNS:
            if re.search(rx, sent):
                out.append((level, soft))
    return out


def degree_required(text: str) -> str | None:
    """Lowest degree level the posting names; '_or_experience' when it's preferred or can be substituted."""
    m = degree_mentions(text)
    if not m:
        return None
    order = [l for l, _ in DEGREE_PATTERNS]
    level = min((l for l, _ in m), key=order.index)
    if all(soft for l, soft in m if l == level) or re.search(r"or equivalent (?:work |professional )?experience|in lieu of (?:a )?degree|equivalent combination", text.lower()):
        level += "_or_experience"
    return level


def clearance_required(text: str) -> str | None:
    t = text.lower()
    if re.search(r"\b(ts/sci|top secret)\b", t):
        return "top_secret"
    if re.search(r"\bsecret\b.*\bclearance\b|\bclearance\b.*\bsecret\b|\bsecret clearance\b", t):
        return "secret"
    if re.search(r"\b(security clearance|clearance required|obtain (?:and maintain )?a clearance)\b", t):
        return "unspecified"
    return None


PAY_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(k)?(?:\s*(?:-|–|to)\s*\$?\s?(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*(k)?)?\s*(?:per|/|an|a)?\s*(hour|hr|year|yr|annually|annual)?", re.I)


def pay_range(text: str) -> tuple[float, float, str] | None:
    """(low, high, "hour"|"year") from the first plausible pay statement, or None."""
    for m in PAY_RE.finditer(text):
        def num(s, k):
            v = float(s.replace(",", ""))
            return v * 1000 if k else v
        lo = num(m.group(1), m.group(2))
        hi = num(m.group(3), m.group(4)) if m.group(3) else lo
        unit = (m.group(5) or "").lower()
        if unit in ("hour", "hr") or (not unit and hi < 300):
            if 10 <= lo <= 300:
                return lo, hi, "hour"
            continue
        if 20_000 <= lo <= 1_000_000:
            return lo, hi, "year"
    return None


US_STATES = {"al","ak","az","ar","ca","co","ct","de","dc","fl","ga","hi","id","il","in","ia","ks","ky","la","me","md","ma",
             "mi","mn","ms","mo","mt","ne","nv","nh","nj","nm","ny","nc","nd","oh","ok","or","pa","ri","sc","sd","tn","tx",
             "ut","vt","va","wa","wv","wi","wy"}


STATE_NAMES = {"alabama","alaska","arizona","arkansas","california","colorado","connecticut","delaware","florida","georgia",
               "hawaii","idaho","illinois","indiana","iowa","kansas","kentucky","louisiana","maine","maryland","massachusetts",
               "michigan","minnesota","mississippi","missouri","montana","nebraska","nevada","new hampshire","new jersey",
               "new mexico","new york","north carolina","north dakota","ohio","oklahoma","oregon","pennsylvania","rhode island",
               "south carolina","south dakota","tennessee","texas","utah","vermont","virginia","washington","west virginia",
               "wisconsin","wyoming","district of columbia"}


def location_area(job, cfg) -> str | None:
    """Workday writes 'USA VA Sterling' or 'US-TX-MCKINNEY-...'; others write 'Sterling, VA'."""
    if non_us(job, cfg):
        return None
    loc = re.sub(r"[-_,;/|~()]", " ", (job.get("location") or "").lower())
    loc = re.sub(r"\s+", " ", loc)
    raw = (job.get("location") or "").lower()
    named_states = {t for t in loc.split() if t in US_STATES}
    if re.search(r",\s*washington\b(?!\s*,?\s*(d\.?\s?c|district))", raw):
        named_states.add("wa")  # "Seattle, Washington" is the state, not D.C.
    # A full state name counts too, except "washington"/"new york", which are also city names
    named_states |= {n for n in STATE_NAMES if n not in ("washington", "new york") and has(loc, n)
                     and not (n == "virginia" and has(loc, "west virginia"))}
    for area, spec in cfg["locations"].items():
        if area.startswith("_"):
            continue
        area_states = set(spec["states"])
        state_ok = not named_states or named_states & area_states or any(has(loc, s) for s in area_states if " " in s)
        if state_ok and any(has(loc, c) for c in spec["cities"]):
            return area
    if (job.get("remote") or has(loc, "remote")) and cfg.get("remote_counts_as_match") and not non_us(job, cfg):
        return "remote"
    return None


def non_us(job, cfg) -> bool:
    loc = (job.get("location") or "").lower()
    return any(has(loc, w) for w in cfg["non_us_words"])


# ---- scoring --------------------------------------------------------------

def score_apply(job, cfg, prof):
    title = job["title"].lower()
    text = f"{job['title']}\n{job['description']}".lower()
    pts, why, gaps, flags = 0, [], [], []

    # Title / level (30)
    lw = cfg["level_words"]
    if any_of(title, lw["too_senior"]):
        pts += 5; gaps.append("title reads as manager/principal level")
    elif any_of(title, lw["stretch"]):
        pts += 18; why.append("senior title: a stretch, worth a read")
    else:
        pts += 30; why.append("title at an attainable level")

    # Experience (20)
    have = prof["experience_years"]["logistics_total"]
    need = years_required(text)
    if need is None:
        pts += 14; why.append("no years requirement stated")
    elif need <= have:
        pts += 20; why.append(f"asks {need}+ yrs, you have {have}")
    elif need <= have + 2:
        pts += 10; gaps.append(f"asks {need}+ yrs (you have {have}, partly part-time Reserve)")
    else:
        gaps.append(f"asks {need}+ yrs")

    # Education (15)
    deg = degree_required(text)
    if deg is None:
        pts += 15
    elif deg.endswith("_or_experience") or deg.startswith("associates"):
        pts += 10; why.append("degree or equivalent experience accepted")
    else:
        pts += 2; gaps.append(f"{deg} degree required")

    # Skills (20)
    hits = any_of(text, prof["skills"])
    pts += min(20, 3 * len(hits))
    if hits:
        why.append("matches: " + ", ".join(hits[:8]))
    vocab = cfg["ils_vocabulary"] if job["family"] == "ils_engineer" else cfg["scm_vocabulary"]
    missing = [v for v in any_of(text, vocab) if v not in prof["skills"] and v not in prof["skills_in_progress"]]
    if missing:
        gaps.append("asks for: " + ", ".join(missing[:8]))

    # Clearance (10)
    clr = clearance_required(text)
    if clr in ("secret", "unspecified"):
        pts += 10; why.append("clearance wanted: your inactive Secret is an edge")
    elif clr == "top_secret":
        poly = has(text, "polygraph") or has(text, "poly")
        pts -= 10 if poly else 0
        gaps.append("Top Secret/SCI" + (" with polygraph" if poly else "") + " required (you held Secret)")
    else:
        pts += 5

    # Location (5)
    area = location_area(job, cfg)
    if area:
        pts += 5; why.append(f"location: {area}")
    else:
        flags.append("outside priority areas")

    # Pay floor: flag, don't drop (most postings don't list pay)
    pay = pay_range(job["description"])
    if pay:
        lo, hi, unit = pay
        floor = prof["pay"]["floor_hourly" if unit == "hour" else "floor_annual"]
        if hi < floor:
            flags.append(f"pay tops out at ${hi:,.0f}/{unit}, below your ${floor:,}/{unit} floor")
            pts -= 15
    return max(0, min(100, pts)), why, gaps, flags, pay, area


def fresh(job, days) -> bool:
    if not job.get("posted"):
        return True  # unknown date: keep, let the reader decide
    return (dt.date.today() - dt.date.fromisoformat(job["posted"])).days <= days


def finance_gaps(bench, cfg, prof, out: Path):
    fv = cfg["finance_vocabulary"]
    n = len(bench)
    deg, fields, skills, certs, yrs = Counter(), Counter(), Counter(), Counter(), []
    for j in bench:
        text = f"{j['title']}\n{j['description']}".lower()
        levels = {l for l, _ in degree_mentions(text)}
        deg.update(levels or {"not stated"})
        fields.update(set(any_of(text, fv["fields"])))
        skills.update(set(any_of(text, fv["skills"])))
        certs.update(set(any_of(text, fv["certifications"])))
        y = years_required(text)
        if y is not None:
            yrs.append(y)
    owned = set(prof["skills"]) | set(prof["skills_in_progress"])

    def table(counter, mark_owned=False):
        rows = [f"| {k} | {v} | {100*v//max(n,1)}% |" + (f" {'in progress / have' if k in owned else 'gap'} |" if mark_owned else "")
                for k, v in counter.most_common()]
        head = "| Requirement | Postings | Share |" + (" You |" if mark_owned else "")
        sep = "|---|---|---|" + ("---|" if mark_owned else "")
        return "\n".join([head, sep, *rows]) if rows else "_none found_"

    by_fam = Counter(j["family"] for j in bench)
    med = sorted(yrs)[len(yrs)//2] if yrs else None
    out.write_text(f"""# Finance gap report: what these roles ask for

Built from {n} live postings ({', '.join(f'{k}: {v}' for k, v in by_fam.items())}).
Benchmark only: these are not application targets.

Median years of experience asked: {med if med is not None else 'not stated'}

## Degree level
{table(deg)}

## Degree fields named
{table(fields)}

## Skills
{table(skills, mark_owned=True)}

## Certifications and licenses
{table(certs)}
""")


def main(path, profile=ROOT / "private" / "profile.json"):
    src = Path(path)
    cfg = json.loads((HERE / "config.json").read_text())
    prof = json.loads(Path(profile).read_text())
    jobs = [json.loads(l) for l in src.read_text().splitlines() if l.strip()]

    # De-duplicate the same posting found by several keyword searches
    seen, uniq = set(), []
    for j in jobs:
        k = (j["company"].lower(), j["title"].lower(), (j.get("location") or "").lower())
        if k not in seen:
            seen.add(k); uniq.append(j)

    applies, bench = [], []
    for j in uniq:
        track, fam = classify(j["title"], cfg)
        if not track:
            continue
        j["track"], j["family"] = track, fam
        if any_of(j["title"].lower(), cfg["exclude_title_words"]):
            continue
        if track == "benchmark":  # any age: more postings make a better gap picture
            bench.append(j)
            continue
        if not fresh(j, cfg["posted_within_days"]) or non_us(j, cfg):
            continue
        s, why, gaps, flags, pay, area = score_apply(j, cfg, prof)
        j.update(score=s, why=why, gaps=gaps, flags=flags, area=area,
                 pay=f"${pay[0]:,.0f}-${pay[1]:,.0f}/{pay[2]}" if pay else "")
        applies.append(j)

    applies.sort(key=lambda j: -j["score"])
    thr = cfg["strong_match_threshold"]
    def blocked(j):
        g = " ".join(j["gaps"])
        return (re.search(r"(bachelors|masters|phd) degree required", g) or "polygraph" in g
                or "manager/principal" in g or re.search(r"asks \d+\+ yrs(?! \(you have)", g))
    strong = [j for j in applies if j["score"] >= thr and j["area"]
              and not any("below your" in f for f in j["flags"]) and not blocked(j)]

    with (src.parent / "scored.csv").open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["score", "strong", "family", "company", "title", "location", "area", "pay", "posted", "why", "gaps", "flags", "url", "id"])
        for j in applies:
            w.writerow([j["score"], "yes" if j in strong else "", j["family"], j["company"], j["title"], j["location"],
                        j["area"] or "", j["pay"], j.get("posted") or "", "; ".join(j["why"]), "; ".join(j["gaps"]),
                        "; ".join(j["flags"]), j["url"], j["id"]])

    lines = [f"# Strong matches ({len(strong)} of {len(applies)} relevant postings, threshold {thr})\n"]
    for i, j in enumerate(strong, 1):
        lines += [f"## {i}. {j['title']}, {j['company']} ({j['score']})",
                  f"{j['location']} · {j['family']} · posted {j.get('posted') or 'date not listed'}" + (f" · {j['pay']}" if j["pay"] else ""),
                  f"- Fits: {'; '.join(j['why'])}",
                  f"- Gaps: {'; '.join(j['gaps']) or 'none flagged'}",
                  f"- {j['url']}\n"]
    (src.parent / "matches.md").write_text("\n".join(lines))
    finance_gaps(bench, cfg, prof, src.parent / "finance_gaps.md")

    print(f"{len(uniq)} unique postings · {len(applies)} SCM/ILS relevant · {len(strong)} strong · {len(bench)} finance benchmarks")
    print(f"-> {src.parent}/scored.csv, matches.md, finance_gaps.md")


if __name__ == "__main__":
    main(*sys.argv[1:3])
