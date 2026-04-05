---
name: arxivterminal
description: CLI tool (arxivterminal) for fetching, searching, and managing arXiv papers locally. Use when working with arXiv papers using the arxivterminal command - fetching new papers by category, searching the local database, viewing papers from specific dates, or managing the local paper database.
---

# arXivTerminal

CLI tool for managing arXiv papers with local database storage.

## Important: Fetch Before Search

`arxiv search` queries the **local database only**. If the database is empty or doesn't contain relevant papers, search will return no results. Always run `arxiv fetch` first to populate the database with papers from the desired categories and time range.

## Quick Reference

### Fetch Papers from arXiv

Download papers and store them in the local database:

```bash
arxiv fetch --num-days N --categories CATEGORIES
```

See [arxivterminal-fetch.md](references/arxivterminal-fetch.md) for detailed options and examples.

### Search Local Database

Search papers already fetched into the local database:

```bash
arxiv search QUERY
arxiv search -e -l 20 QUERY    # experimental semantic search, limit 20
```

**Note:** `arxiv search` launches an interactive UI. It is not suitable for non-interactive (piped/scripted) use.

See [arxivterminal-search.md](references/arxivterminal-search.md) for search options.

### Show Papers by Date

```bash
arxiv show --days-ago N
```

See [arxivterminal-show.md](references/arxivterminal-show.md) for details.

### Database Statistics

```bash
arxiv stats
```

See [arxivterminal-stats.md](references/arxivterminal-stats.md) for output format.

### Database Management

- Use `arxiv delete-all` to reset the database
- See [arxivterminal-management.md](references/arxivterminal-management.md) for database location and backup procedures

## Data Storage

- **Database**: `~/Library/Application Support/arxivterminal/papers.db`
- **Logs**: `~/Library/Logs/arxivterminal/arxivterminal.log`

## Common arXiv Categories

Physics:
- `cond-mat.str-el` — Strongly Correlated Electrons
- `cond-mat.stat-mech` — Statistical Mechanics
- `quant-ph` — Quantum Physics
- `hep-th` — High Energy Physics (Theory)

CS/ML:
- `cs.AI` — Artificial Intelligence
- `cs.LG` — Machine Learning
- `cs.CL` — Computation and Language

Math:
- `math-ph` — Mathematical Physics
- `math.NA` — Numerical Analysis

## Common Workflows

### Daily Research Workflow

```bash
# Step 1: Fetch recent papers into local DB
arxiv fetch --num-days 1 --categories quant-ph,cond-mat.str-el

# Step 2: Search the fetched papers
arxiv search -e -l 20 "variational Monte Carlo"
```

### Weekly Review

```bash
arxiv fetch --num-days 7 --categories cs.AI,cs.LG,quant-ph
arxiv stats
```
