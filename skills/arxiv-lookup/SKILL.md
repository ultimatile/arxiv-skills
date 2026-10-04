---
name: arxiv-lookup
description: Look up arXiv paper metadata via the arXiv API. Use when you need to get a journal DOI from an arXiv ID (for OpenAlex integration), or find an arXiv ID from a title/keyword search (for arxiv-doc-builder). Requires the `arxiv` Python package.
---

# arXiv Lookup

Lightweight scripts for querying the arXiv API directly via `arxiv.py`.

## Scripts

In the commands below, `SKILL_DIR` is a placeholder, not a shell variable: replace it with the absolute path of the directory this SKILL.md is in. Keep the double quotes around the path, so a path containing spaces stays one argument. `--no-project` keeps uv from building the environment from a project in your working directory. The commands then run from any working directory.

### Get Journal DOI from arXiv ID

```bash
uv run --no-project --with arxiv "SKILL_DIR/scripts/get_doi.py" <arxiv_id>
```

- Returns the journal DOI if available (exit 0), or exits with error (exit 1) if not found
- This is the **journal-assigned DOI**, not the arXiv-assigned DOI (`10.48550/arXiv.{id}`)
- arXiv-assigned DOI can be constructed mechanically: `10.48550/arXiv.<id>` — no API call needed

### Search arXiv and Get IDs

```bash
uv run --no-project --with arxiv "SKILL_DIR/scripts/search_id.py" <query> [max_results]
```

- Searches the arXiv API directly (no local database)
- Returns tab-separated `arxiv_id\ttitle` lines
- Default: 5 results, sorted by relevance
- Query supports arXiv API field prefixes: `ti:` (title), `au:` (author), `abs:` (abstract), `cat:` (category)
- Use quotes for exact phrases: `ti:"Attention Is All You Need"`
- Combine with AND/OR/ANDNOT: `ti:transformer AND cat:cs.CL`

## Integration Notes

- **OpenAlex**: Use `get_doi.py` to obtain journal DOIs for OpenAlex queries
- **arxiv-doc-builder**: Use `search_id.py` to find arXiv IDs, then pass to arxiv-doc-builder
