# Troubleshooting: glossaries / cleveref and other unknown-arity macros

Symptom: a fast `unexpected (` / `unexpected [` error, often reported at `\begin{document}` (the real cause is elsewhere — pandoc parsed to a boundary). Cause: a heavily-used package whose commands take **optional arguments** pandoc doesn't know the arity of — most commonly `glossaries` / `glossaries-extra` (`\gls`, `\glspl`, `\glsxtrlong`, …, including the `\gls[prereset]{key}` optional-arg form) and `cleveref` (`\cref`). pandoc mis-counts the braces it should consume and breaks once enough body follows.

Fix: inject **arity-correct `\providecommand` stubs** (optional-argument-tolerant) just before `\begin{document}`. `\providecommand` only defines them because pandoc never loaded the real package:

```latex
\makeatletter
\providecommand{\gls}[2][]{#2}\providecommand{\glspl}[2][]{#2}
\providecommand{\Gls}[2][]{#2}\providecommand{\Glspl}[2][]{#2}
\providecommand{\glsxtrlong}[2][]{#2}\providecommand{\glsxtrlongpl}[2][]{#2}
\providecommand{\glsxtrshort}[2][]{#2}\providecommand{\glsxtrshortpl}[2][]{#2}
\providecommand{\glsentryshort}[1]{#1}\providecommand{\glsentrylong}[1]{#1}
\providecommand{\glslink}[3][]{#3}\providecommand{\glsadd}[2][]{}
\providecommand{\cref}[1]{#1}\providecommand{\Cref}[1]{#1}
\makeatother
```

Then re-run `convert-paper` and check that the stubs survived, as `references/source-edits.md` describes.

Quality note: this expands `\gls{AF}` to its **key** (`AF`), not the glossary long form ("activation function") — pandoc cannot resolve the glossary database. Keys are usually readable (`ReLU`, `NN`, `tanh`), which is acceptable for an implementation-reference doc; `\cref{sec:x}` likewise renders as the label `sec:x`, not a link.

This is a *targeted* exception to SKILL.md's rule against broad preprocessing: stubbing a fixed set of known unknown-arity commands, not rewriting the document.
