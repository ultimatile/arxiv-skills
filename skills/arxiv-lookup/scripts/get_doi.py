#!/usr/bin/env python3
"""Get journal DOI for an arXiv paper by its ID."""

import sys

import arxiv


def get_doi(arxiv_id: str) -> str | None:
    """Return the journal DOI for the given arXiv ID, or None if not available."""
    client = arxiv.Client()
    search = arxiv.Search(id_list=[arxiv_id])
    results = list(client.results(search))
    if not results:
        print(f"Paper not found: {arxiv_id}", file=sys.stderr)
        sys.exit(1)
    return results[0].doi


def main() -> None:
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <arxiv_id>", file=sys.stderr)
        sys.exit(1)

    arxiv_id = sys.argv[1]
    doi = get_doi(arxiv_id)
    if doi:
        print(doi)
    else:
        print(f"No journal DOI found for {arxiv_id}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
