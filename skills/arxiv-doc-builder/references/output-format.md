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
metadata record behind the record-derived fields was read, and on
`metadata_source`, which records where that record came from. The lookup asks
arXiv's own API first (`metadata_source: "arxiv"`) and falls back to the
registration arXiv files at DataCite for the paper's DOI,
`10.48550/arXiv.<id>` (`metadata_source: "datacite"`), when arXiv does not
answer with a record. The two records do not carry the same fields, so a null
is read against the one that answered:

- `ok`. A record was read — `metadata_source` names which one — and a null
  field is a **confirmed absence from that record**. Under `arxiv` a null
  `journal` and a null `doi` together support a "preprint, not published yet"
  reading. Either one alone does not: an author can register a DOI without
  entering a journal reference, or the reverse. Under `datacite` a
  null `journal` says nothing of the sort: that record has no journal-reference
  field at all.
- `unavailable`. Neither source supplied a record. Both attempts failed, or the
  time limit the lookup runs under ran out, or DataCite has no record for the
  id, or the id names a
  revision later than the latest one DataCite lists. A null field is therefore
  **unknown** rather than a confirmed absence. The conversion names what each
  source said on stderr as it runs.
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
doi: "10.1145/1234567.1234568"   # or bare `doi:` (null)
journal: "Phys. Rev. D 76, 013009 (2007)"   # or null
source_type: "latex"             # or "pdf"
metadata_status: "ok"            # or "unavailable" / "not_requested"
metadata_source: "arxiv"         # or "datacite", or null
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
  arXiv announces it, so under `metadata_source: "datacite"` the record can
  trail what arXiv serves. That lag is the one case a recorded revision
  outranks the one the record names, and all four of its conditions hold
  together: DataCite answered, the id was given without a version, a source is
  cached on disk, and `.arxiv-fetch.json` already records a later revision of
  the same paper. The fetch step then keeps and converts the recorded revision,
  and `version` still names the record's older one; the revision on disk is the
  one `.arxiv-fetch.json` records. When arXiv answered, the revision it names
  is authoritative and a later recorded one is replaced.
  A withdrawn revision is still the paper's latest: `version` names it, the
  abstract reads as the withdrawal notice, and `published` stays the first
  revision's date.
  For a paper arXiv serves as a PDF alone, no cached source stands behind the
  recorded revision, so the revision follows whichever source answered: while
  DataCite trails a new revision, a run that falls back to it records the
  earlier revision and downloads that PDF again, and a later run that reaches
  arXiv moves both forward again. It settles once DataCite lists the new
  revision.
- `published` is the paper's date (`YYYY-MM-DD`); `conversion_date` is when the
  conversion ran (UTC-aware ISO 8601). They are deliberately distinct.
- `doi` holds the published DOIs the answering record carries, spelled as that
  record stores them, except that unprintable characters are dropped and
  whitespace is collapsed and trimmed. The two records carry different numbers
  of them. Under `arxiv` the key holds at most the one DOI the author
  registered for the paper. Under `datacite` it holds every DOI that record
  lists as a version of the paper, separated by spaces, so the value can name
  several. Resolving a DOI the answering record does not carry is the
  arxiv-lookup skill's job, not this converter's.
- `journal` is the paper's journal reference, as the author entered it on
  arXiv. Only arXiv's record carries one, so the key is null under
  `metadata_source: "datacite"` whatever the paper's publication history.
- `categories` lists the arXiv category codes the answering record gives, in
  its order. Which codes of an alias pair (`math-ph` and `math.MP`, say) appear
  is likewise whatever that record lists.
- `primary_category` under `arxiv` is the category that record marks as
  primary. Under `datacite` it is the first code in `categories`: DataCite's
  record marks none as primary, and its first code matched the primary category
  on the arXiv abstract page in every record compared, though DataCite does not
  document that ordering.
- `metadata_source` names the record the fields above came from, and is null
  exactly when `metadata_status` is not `ok`.
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
