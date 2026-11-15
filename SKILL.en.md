---
name: read-anything
description: Use when only a human can answer — experience, reputation, insider detail, warnings, whether something will block you. Search for leads and entities first, then use ra.py to read 小红书 / 知乎 / 微博 / CSDN / 贴吧 / Reddit in people's own words. Read-only. Never log in for the user.
---

# When to use it

Not "the user mentioned Xiaohongshu". When only a human can answer. Three signals:

- The question is "worth it / what's it really like / does anyone / how do I choose / will it block me"
- Search returns only official pages, admissions pages, job descriptions — institutions talking, not people
- The user is making a personal decision, not looking up a definition

Lookups for APIs, syntax, version numbers: not this tool.

# Four steps

**1. Search for leads.** This step is not for answering. It is for extracting entities.

```
web_search "<question>"        →  5–10 hits: news, reports, official pages
web_fetch <two densest hits>   →  pull out names, companies, projects, policies, numbers
```

**2. Rewrite.** A spoken question is not a search query.

Bad: "how do I prepare for embedded roles at big companies"
Good: "embedded internship interview"

**3. Dispatch.**

```bash
python -m read_anything.ra suggest "<question>"
```

You get intent, entities, and a query per site. Run them.

| Site | Ask it about |
|---|---|
| Xiaohongshu | campus life, rent, job-hunt complaints, visa experience |
| Zhihu | industry judgment, technical arguments, policy reading |
| Reddit | the English-speaking market, inside companies, visa timelines |
| Bilibili | tutorials, reviews |
| Tieba | anonymous candor: exam progress, school life |

**4. Subtract before you answer.** Do not hand over 20 links. Give three things:

- **Consensus**: 3+ independent sources saying the same thing
- **Disagreement**: who says the opposite, and whether time, status, or region explains it
- **Confidence**: every claim carries a source and a date

# Hard rules

1. Every conclusion points back to a specific post. Give the URL.
2. **One post is not a fact.** It is one person saying so. Three independent sources make a consensus.
3. When a fetch fails, say which step failed and why. Do not substitute another site's conclusion.
4. Never log in for the user. Never ask for a password in chat.
5. When a platform blocks you, fall back to public search and label the gap: "no first-hand account here".

# When a site blocks you

`ra.py` prints `⚠️ / 🔒` and leads with **0_handoff**: control comes back to you with queries you can run.
Search, then bring the URL back to `read_url`. Only if search fails too, go ①→②→③.

1. **Find a mirror / a no-login entry.** Same content, different door. Try once — mirrors die fast.
2. **Switch site.** Same question, another room.
3. **Find a reprint.** Search the exact title.

If all three fail, say so. **"No data" is a valid answer. A made-up one is not.**

# Failure reference

| Symptom | Cause | Do this |
|---|---|---|
| `🔒 needs login` | not logged in, or expired | have the user run `login.py <site>` |
| `⚠️ first result unchanged` | search_url template is wrong | stop; don't trust the rows |
| `0 results` | selector broke / blocked | switch site or go back to web search |
| Reddit 403/429 | IP rate-limited | wait a few minutes, or read single posts only |
