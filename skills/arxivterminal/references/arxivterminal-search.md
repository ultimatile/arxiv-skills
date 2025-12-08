# arxiv search

Search papers in the local database.

## Usage

```bash
arxiv search [OPTIONS] QUERY
```

## Options

- `-e, --experimental` - Use experimental LSA (Latent Semantic Analysis) relevance search
- `-f, --force` - Force refresh of the experimental model
- `-l, --limit INTEGER` - Maximum number of results to return

## Examples

```bash
# Simple search
arxiv search "transformer"

# Experimental semantic search with limit
arxiv search -e -l 10 "attention mechanism"

# Force model refresh for experimental search
arxiv search -e -f "neural networks"

# Search for specific topics
arxiv search "large language models"
arxiv search -e "multimodal learning"
```

## Search Modes

### Standard Search
Basic keyword matching in paper titles and abstracts.

### Experimental Search (`-e`)
Uses Latent Semantic Analysis (LSA) for semantic similarity search. This can find papers that are conceptually related even if they don't contain exact keyword matches.

## Notes

- Search only queries papers already in your local database
- Use `arxiv fetch` first to populate the database
- Experimental search may take longer on first run as it builds the LSA model
- Use `-f` flag to rebuild the model if search results seem outdated
