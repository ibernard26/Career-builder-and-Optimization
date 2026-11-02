# Career-builder-and-Optimization
Optimizing my resume to transition me from ILS work into Finance

## Job search pipeline (`jobsearch/`)

| Step | Where | What |
|---|---|---|
| 1. Find | cloud | `fetch.py` pulls this week's postings from company job boards (Greenhouse, Lever, Ashby, Workday) and USAJOBS |
| 2. Score | cloud | `score.py` ranks ILS / supply chain / logistics roles against the profile, and tallies finance role requirements into a gap report |
| 3. Draft | cloud | Claude reads each strong match and drafts the application answers into a packet |
| 4. Fill | your computer | Claude Desktop with Playwright fills the forms and stops before Submit ([APPLY_ON_DESKTOP.md](jobsearch/APPLY_ON_DESKTOP.md)) |

Two tracks:
- **Apply:** ILS engineer, supply chain analyst, logistician, logistics lead. Priority areas are NYC metro, Syracuse, Philadelphia and the DC area. Pay floor $50/hr or $95k/yr.
- **Benchmark:** quant analyst, hedge fund analyst, equity and derivatives analyst. Read only to find education, skill and certification gaps. Never applied to.

`companies.csv` is the starter list (about 200 companies). Set `keep` to `no` for any you
don't want. `discover.py` fills in which job board each company uses.

```bash
cd jobsearch
python3 discover.py
python3 fetch.py
python3 score.py ../private/runs/$(date +%F)/jobs.jsonl
python3 -m unittest discover -s tests
```

Personal data (resume, profile, scored jobs, drafts) lives in `private/`, which git ignores.
This repo is public.
