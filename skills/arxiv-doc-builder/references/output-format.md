# Output Format Specification

This document has two kinds of content:

- **Frontmatter (code-generated).** The YAML frontmatter at the top of every
  converted paper is emitted by `arxiv_doc_builder/arxiv_metadata.py`
  (`build_frontmatter`), which is the single source of truth for its schema.
  The block below documents that schema; the code, not this prose, defines it.
- **Body formatting (agent-facing).** Everything after the frontmatter — math,
  figures, tables, code, citations — is guidance for an agent cleaning up or
  authoring the Markdown by hand. There is no code enforcing it, so it lives
  here.

## Frontmatter

`build_frontmatter` writes one YAML block keyed identically on both conversion
paths (LaTeX and PDF). The schema is **total**: every key is always present.
A value that is not known renders as YAML null (a bare `key:`), which a parser
reads as `None` and not as a missing key. The one exception is `categories`,
which renders as an empty list (`categories: []`) instead.

In the rest of this section, a null field includes an empty `categories`.

What a null means depends on `metadata_status`, which records whether a usable
metadata record behind the record-derived fields was read. That record is the
one arXiv registers at DataCite for the paper's DOI, `10.48550/arXiv.<id>`:

- `ok`. The record was read, and a null field is a **confirmed absence**. The
  record exists and reports no value there, which supports a "preprint, no
  journal DOI" reading.
- `unavailable`. The lookup failed or did not finish in time, DataCite has no
  record for the id, or the id names a revision later than the latest one the
  record lists. No
  usable record reached the converter, which leaves a null field **unknown**
  instead of a confirmed absence. The conversion names the
  cause on stderr as it runs.
- `not_requested`. The conversion ran with no arXiv id, and the record was
  never sought. A null field is unknown here as well, for a different reason
  than under `unavailable`, where the question was put and no record came back.
  Among the manual PDF conversion scripts, `convert_pdf_simple.py` is the one
  that takes an `--arxiv-id`, and documents from the rest always carry this
  token.

```yaml
---
title: "Paper Title"
authors: "Author A, Author B, Author C"
arxiv_id: "2409.03108"
version: "2409.03108v2"
published: "2024-09-04"
primary_category: "cs.AI"
categories:
  - "cs.AI"
  - "cs.CL"
doi: "10.1145/1234567.1234568"   # or bare `doi:` (null); see metadata_status
source_type: "latex"             # or "pdf"
metadata_status: "ok"            # or "unavailable" / "not_requested"
conversion_date: "2025-12-08T10:00:00+00:00"
abstract: |-
  Single-paragraph abstract, whitespace-normalized.
---
```

Field notes:

- `version` is the full versioned arXiv id (e.g. `2409.03108v2`, legacy
  `hep-th/9901001v3`). For an id given without a version it names the latest
  revision the record lists. For an id given with one it names that revision,
  while every other record-derived field still describes the record, which
  follows the latest revision. DataCite lists a new revision a few hours after
  arXiv announces it. When `.arxiv-fetch.json` already records a later
  revision of an id given without a version, the fetch step keeps and converts
  that revision, and `version` still names the record's older one. The
  revision on disk is the one `.arxiv-fetch.json` records.
- `published` is the paper's date (`YYYY-MM-DD`); `conversion_date` is when the
  conversion ran (UTC-aware ISO 8601). They are deliberately distinct.
- `doi` holds the DOIs the record lists as versions of the paper, separated by
  spaces and spelled as the record stores them, except that unprintable
  characters are dropped and whitespace is collapsed and trimmed.
  Resolving a
  DOI that the record does not carry is the arxiv-lookup
  skill's job, not this converter's.
- `categories` lists the arXiv category codes as DataCite's record gives them,
  in the record's order. For an alias pair such as `math-ph` and `math.MP`, the
  record carries one code, the one the paper's arXiv abstract page shows.
- `primary_category` is the first code in `categories`. DataCite's record marks
  no category as primary. Its first code has matched the primary category on the
  arXiv abstract page in every record compared, but DataCite does not document
  that ordering.
- Two fields survive on local sources when no record backs the document.
  `title` comes from the LaTeX `\title` or the PDF's embedded title on either
  path, and `authors` from the PDF's embedded author on the PDF path, staying
  null on the LaTeX path. Every other record-derived field renders as null, and
`categories` as `[]`.
  A populated `title` or `authors` is therefore no evidence that the record was
  read, and `metadata_status` is what answers that.

## Body Structure

After the frontmatter, the converted body typically looks like:

```markdown
# Paper Title

## Abstract

Abstract text (when the source carries it inline).

## Table of Contents

- [1. Introduction](#1-introduction)
- [2. Related Work](#2-related-work)
- ...

---

## 1. Introduction

Content...

### 1.1 Subsection

Content...

---

## References

[1] Author et al. Title. Conference/Journal, Year.
```

The abstract is also captured in the frontmatter (`abstract:`), so a consumer
can read it from a fixed location even when the body extraction drops it — a
common case in the PDF-only fallback.

## Mathematics Formatting

### Inline Math

Use single `$` delimiters:
```markdown
The learning rate $\alpha$ controls convergence.
```

### Display Math

Use double `$$` delimiters:
```markdown
$$
\mathcal{L}(\theta) = \sum_{i=1}^n \ell(y_i, f_\theta(x_i))
$$
```

### Numbered Equations

```markdown
$$
E = mc^2 \tag{1}
$$
```

## Figure Handling

### With Available Images

```markdown
![Architecture diagram](figures/fig1.png)
*Figure 1: Overview of the proposed architecture*
```

### Images Not Extracted

```markdown
**Figure 1:** Overview of the proposed architecture
*[Image not extracted - see PDF page X]*
```

## Table Formatting

Standard Markdown tables:

```markdown
| Method | Accuracy | F1 Score |
|--------|----------|----------|
| BERT   | 92.3     | 89.1     |
| GPT-2  | 91.8     | 88.5     |

*Table 1: Performance comparison on benchmark dataset*
```

## Code Blocks

For algorithms or code:

````markdown
```python
def train_model(data, epochs):
    for epoch in range(epochs):
        loss = compute_loss(data)
        update_params(loss)
```
````

## Citations

### In-text Citations

Prefer readable format:
```markdown
This approach was introduced by Smith et al. [1].
```

Or keep LaTeX format if context is needed:
```markdown
The method \cite{smith2023} shows promising results.
```

### References Section

```markdown
## References

[1] Smith, J., Doe, A. (2023). Title of Paper. *Conference Name*, pp. 123-456.

[2] Jones, B. (2022). Another Paper. *Journal Name*, 15(3), 789-801.
```

## File Organization

```
papers/
└── 2409.03108/
    ├── 2409.03108.md                # Main document (frontmatter + paper content)
    ├── .arxiv-fetch.json            # Fetch-side version record (drift detection)
    ├── figures/
    │   ├── fig1.png
    │   ├── fig2.png
    │   └── ...
    ├── images/                      # PDF to image conversion (if used)
    │   ├── page_001_full.png
    │   ├── page_001_col1.png
    │   └── ...
    ├── source/                      # Original LaTeX (if available)
    │   ├── main.tex
    │   └── ...
    └── pdf/
        └── 2409.03108.pdf           # Original PDF
```

The provenance metadata lives in the document's YAML frontmatter (see above).
`.arxiv-fetch.json` is an internal sidecar used only for version-drift
detection (`{"version": "2409.03108v2"}`); it is not the metadata surface a
consumer reads.

The sidecar records a version only when the fetch obtained material and the
metadata record supplied one. A run that obtained material without a version
writes nothing to it, leaving any earlier value in place, and says so on
stderr. A run that obtained no material at all exits non-zero.
