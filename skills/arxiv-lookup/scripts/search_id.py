#!/usr/bin/env python3
"""Search arXiv and return matching paper IDs with titles."""

import sys

import arxiv


def search_arxiv(query: str, max_results: int = 5) -> list[arxiv.Result]:
    """Search arXiv API directly and return results."""
    client = arxiv.Client()
    search = arxiv.Search(
        query=query,
        max_results=max_results,
        sort_by=arxiv.SortCriterion.Relevance,
    )
    return list(client.results(search))


def main() -> None:
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <query> [max_results]", file=sys.stderr)
        sys.exit(1)

    query = sys.argv[1]
    max_results = int(sys.argv[2]) if len(sys.argv) > 2 else 5

    results = search_arxiv(query, max_results)
    if not results:
        print(f"No results for: {query}", file=sys.stderr)
        sys.exit(1)

    for r in results:
        # entry_id is like http://arxiv.org/abs/1234.56789v1 — extract the ID
        arxiv_id = r.entry_id.split("/abs/")[-1]
        # Strip version suffix for cleaner output
        base_id = arxiv_id.rsplit("v", 1)[0]
        print(f"{base_id}\t{r.title}")


if __name__ == "__main__":
    main()
