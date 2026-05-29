# ProPublica — Research Skill Guide

## What this skill is

ProPublica is a nonprofit investigative news organization focused on exposing
abuses of power and betrayals of public trust.  It is known for long-form
accountability journalism on government, health care, criminal justice, and
financial industry.  This skill also provides access to ProPublica's open data
repository.

**AllSides Media Bias Rating: Lean Left**

## Beat coverage

- Government accountability and corruption
- Health care (hospital rankings, billing practices)
- Criminal justice and sentencing disparities
- Environment and corporate pollution
- Campaign finance and lobbying
- Education
- Financial industry and predatory practices

## Access method

- Main RSS feed at `feeds.propublica.org/propublica/main` (free, no key)
- Web search at `propublica.org/search` (fallback)
- Nonprofit Explorer API at `projects.propublica.org/nonprofits/api/v2` (free)
- Congress API and Campaign Finance API (require a free ProPublica API key)

## Tools

### `search_articles(ctx, query, *, max_results=10)`
Searches ProPublica RSS and web for articles matching ``query``.

### `fetch_article(ctx, url)`
Fetches a single ProPublica article URL through the broker.

### `search_data_repo(ctx, query, *, dataset="nonprofits", max_results=10)`
Searches ProPublica open data.  Available datasets:
- ``nonprofits`` — IRS Form 990 data for 1.8M+ nonprofits (no key needed)
- ``congress`` — bills, votes, members (requires free API key)
- ``campaign_finance`` — FEC filings (requires free API key)

### `list_recent_in_topic(ctx, topic, *, since=None, max_results=10)`
Watchable tool.  Topics: top, main, politics, health, criminal_justice,
environment.

## Bias and limitations

- **Bias rating: Lean Left** (AllSides, 2024).
- Editorial focus on institutional accountability from a progressive perspective.
- Exceptional depth for investigative subjects; lighter on breaking news.
- Open data tools are the unique differentiator vs. other news skills.
- Nonprofit Explorer data may be 1–2 years behind due to IRS processing lag.

## Citation

Cite as: ProPublica, [article title], [date], propublica.org
