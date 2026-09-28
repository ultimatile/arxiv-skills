# Hand Edits to the Source

The fetch step reuses the cached source, but when the metadata lookup reports a revision that
`.arxiv-fetch.json` does not record (a different one, or any at all when the file records none), it
usually downloads again, deleting `source/` and every edit made to it.

The fetch step's output tells you what happened to the edit:

- **It printed `✓ Source already present ...`.** The source was reused and the edit is intact.
- **It printed `Fetching source from ...` and its summary lists `✓ LaTeX source available`.** The
  source was downloaded again and the edit is gone. Apply the edit again and re-run.
- **It printed `Fetching source from ...` and its summary does not list `✓ LaTeX source
  available`.** The source was deleted and not replaced. Re-run once with the same arguments. If the
  summary then lists `✓ LaTeX source available`, apply the edit again and re-run. If it still does
  not, stop re-running: the source cannot be downloaded now. When the summary lists
  `✓ PDF available`, the paper can still be converted from the PDF, as
  `references/pdf-conversion.md` describes.
