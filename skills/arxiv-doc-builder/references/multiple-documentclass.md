# Troubleshooting: Multiple \documentclass Files

Some arXiv papers (e.g., PRL with supplemental material) contain multiple `.tex` files, each with its own `\documentclass`. Automatic selection is unreliable in this case — the canonical example is `1911.04882`, which ships both the main PRL paper and an independent PRL supplement, and either can convert successfully. Since pandoc succeeding is not evidence that the selected file is the correct entry point, `convert-paper` refuses to guess: it fails explicitly with **exit code 2** and lists all candidates.

Example failure output:

```
Error: Found 2 files with \documentclass in /path/to/1911.04882/source:
  - /path/to/1911.04882/source/main_paper.tex
  - /path/to/1911.04882/source/supplemental_material.tex

Main .tex selection is ambiguous. Re-run with --tex-file pointing at the correct file, e.g.:
  convert-paper <ARXIV_ID> --tex-file /path/to/1911.04882/source/main_paper.tex

If you originally passed --output-dir, include the same value in the re-run.
```

To resolve, re-run `convert-paper` with `--tex-file` pointing at the correct main file:

```bash
convert-paper 1911.04882 --tex-file /path/to/1911.04882/source/main_paper.tex
```

If the original run used `--output-dir`, pass the same value again so that `convert-paper` reconstructs the correct paper directory.
