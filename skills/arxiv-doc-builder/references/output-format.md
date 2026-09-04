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
reads as `None` and not as a missing key.

What a null means depends on `metadata_status`, which records whether the arXiv
record behind the arXiv-derived fields was read:

- `ok`. The record was read, and a null field is a **confirmed absence**. arXiv
  holds this paper's record and reports no value there, which supports a
  "preprint, no journal DOI" reading.
- `unavailable`. The request failed, arXiv returned no record for the id, or
  arXiv rejected the id. No record reached the converter, which leaves a null
  field **unknown** instead of a confirmed absence. The conversion names the
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
journal: "Proc. ACM, 2024"       # or bare `journal:` (null)
source_type: "latex"             # or "pdf"
metadata_status: "ok"            # or "unavailable" / "not_requested"
conversion_date: "2025-12-08T10:00:00+00:00"
abstract: |-
  Single-paragraph abstract, whitespace-normalized.
---
```

Field notes:

- `version` is the full versioned arXiv id (e.g. `2409.03108v2`, legacy
  `hep-th/9901001v3`), recording which revision was read.
- `published` is the paper's date (`YYYY-MM-DD`); `conversion_date` is when the
  conversion ran (UTC-aware ISO 8601). They are deliberately distinct.
- `doi` / `journal` are whatever arXiv's own record carries. Resolving a DOI
  that arXiv does not carry (e.g. via OpenAlex) is the arxiv-lookup skill's job,
  not this converter's.
- When no arXiv record backs the document the schema still holds, and two
  fields are filled from local sources instead. `title` comes from the LaTeX
  `\title` or the PDF's embedded title on either path. `authors` comes from the
  PDF's embedded author on the PDF path, and stays null on the LaTeX path.
  Every other arXiv-sourced field renders as null.
- A populated `title` or `authors` is therefore no evidence that arXiv was
  reached. `metadata_status` is what answers that, carrying `unavailable` when
  the record could not be read and `not_requested` when no id was supplied.

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
consumer reads. It is written only when the fetch obtained material *and* the
arXiv record supplied a version. Two situations leave it absent or holding an
older value, namely a record that could not be read and a record read without a
version. A fetch that obtained material in either situation prints the reason on
stderr, because it otherwise looks like an ordinary success. A fetch that
obtained no material at all exits non-zero on its own.
