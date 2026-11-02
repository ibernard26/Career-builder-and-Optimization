# Filling applications on your own computer

The cloud session finds jobs, scores them and drafts every answer. Filling the forms happens
on your computer, in a browser you can see, so you can read each application and press
Submit yourself. Claude never presses Submit.

## 1. One-time setup: Playwright in Claude Desktop

1. Install Node.js (LTS) from nodejs.org if `npx --version` doesn't work in a terminal.
2. In Claude Desktop open **Settings → Developer → Edit Config**. That opens
   `claude_desktop_config.json` (Mac: `~/Library/Application Support/Claude/`,
   Windows: `%APPDATA%\Claude\`). Paste this, keeping any servers already there:

```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest"]
    }
  }
}
```

3. Quit and reopen Claude Desktop. The Playwright tools appear in the tools menu.
   No `--headless` flag on purpose: the browser window stays visible.

## 2. Each batch

You'll get an **application packet** from the cloud session: a folder with your resume PDF,
`packet.md` (one section per job: link, the drafted answers, anything that needs your input)
and `tracker.csv`. Save it somewhere like `~/job-packets/2026-11-09/`.

Then paste this into a new Claude Desktop chat, with the folder path filled in:

> Read `~/job-packets/DATE/packet.md`. For each job in order:
> 1. Open its link with Playwright and click through to the application form.
> 2. Fill every field you can from that job's section of the packet. Upload `resume.pdf`
>    where a resume is asked for. Use the drafted answers word for word.
> 3. If a question isn't covered by the packet, leave it blank and list it for me. Never make
>    up an answer, a date, a number or a reference.
> 4. Leave voluntary self-identification questions (gender, race, disability, veteran
>    status) for me to answer.
> 5. **Never click Submit, Apply, Send or Finish.** Stop on the final review page, tell me
>    the job is ready, and wait for me to say "next".
> 6. If the site asks me to sign in or make an account, or shows a CAPTCHA, stop and let me do it.

After you press Submit, mark the job `submitted` in `tracker.csv`.

## Notes

- Workday sites (most defense primes) need an account per company. Use one password
  manager entry per site.
- USAJOBS applications go through login.gov and USA Hire assessments, so do those yourself.
  The packet still gives you the drafted text to paste.
- Company career sites only. LinkedIn and Indeed don't allow automated filling.
