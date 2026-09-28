# Troubleshooting: pandoc Conversion Failures

When pandoc fails on a LaTeX source, the error may point to `\end{document}` with `unexpected \end`. This means pandoc's parser broke down due to a syntax issue elsewhere — `\end{document}` itself is not the cause. Keep to SKILL.md's rule against broad preprocessing.

## Diagnosis steps

1. **Binary search for the failing line.** Extract the body (`\begin{document}` to `\end{document}`), then test pandoc with increasing prefixes to find the first line that causes failure.
2. **Check that line for brace mismatches.** The most common cause is an unbalanced `{` or `}` in the LaTeX source. LaTeX's TeX engine silently tolerates these, but pandoc's structured parser does not.
3. **Fix only the mismatch and re-run `convert-paper`.** A single-character fix (e.g., removing an orphaned `{`) is usually sufficient. Then check that the fix survived, as `references/source-edits.md` describes.

## Example

The source `(see, e.g., {\cite{makhlin})` has an unmatched `{`. LaTeX compiles fine but pandoc fails. Fix: remove the stray `{`.
