# Output Format Specification

## Standard Markdown Structure

Generated documentation follows this template:

```markdown
# [Paper Title]

**Authors:** [Author list]
**arXiv ID:** [ARXIV_ID]
**Published:** [Date]
**Categories:** [Categories]

## Abstract

[Abstract text]

## Table of Contents

- [1. Introduction](#1-introduction)
- [2. Related Work](#2-related-work)
- ...

---

## 1. Introduction

[Content...]

### 1.1 Subsection

[Content...]

## 2. Related Work

[Content...]

---

## Figures

### Figure 1: [Caption]

![Caption](figures/fig1.png)

[Figure description if available]

---

## References

[1] Author et al. Title. Conference/Journal, Year.
[2] ...
```

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

## Metadata Header

Include at top of document:

```markdown
---
title: "Paper Title"
authors: "Author A, Author B, Author C"
arxiv_id: "2409.03108"
published: "2024-09-04"
categories: "cs.AI, cs.CL"
source_type: "latex"  # or "pdf"
conversion_date: "2025-12-08"
---
```

## File Organization

```
papers/
└── 2409.03108/
    ├── 2409.03108.md           # Main document
    ├── figures/
    │   ├── fig1.png
    │   ├── fig2.png
    │   └── ...
    ├── source/                 # Original LaTeX (if available)
    │   ├── main.tex
    │   └── ...
    └── pdf/
        └── 2409.03108.pdf      # Original PDF
```

## Quality Indicators

Add notes for conversion quality:

```markdown
---

## Conversion Notes

- **Source:** LaTeX source available
- **Math:** All equations preserved in LaTeX notation
- **Figures:** 12 figures extracted and embedded
- **Tables:** 3 tables converted to Markdown
- **Quality:** High - complete LaTeX source conversion

---
```

Or for PDF conversion:

```markdown
## Conversion Notes

- **Source:** PDF only (no LaTeX source)
- **Math:** Complex equations marked as [see PDF]
- **Figures:** 8 of 10 figures extracted
- **Tables:** Manual verification recommended
- **Quality:** Medium - PDF extraction limitations

---
```
