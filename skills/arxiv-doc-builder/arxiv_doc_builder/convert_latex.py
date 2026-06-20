#!/usr/bin/env python3
"""
Convert LaTeX source to Markdown.

Uses pandoc for conversion, with post-processing for better formatting.
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Optional

# Importable both as a package member and as a bare script. Narrow to
# ModuleNotFoundError + name check so an ImportError raised *inside*
# arxiv_id.py isn't silently masked by the script-mode fallback.
try:
    from arxiv_doc_builder.arxiv_id import safe_arxiv_id, validate_arxiv_id
    from arxiv_doc_builder.arxiv_metadata import build_frontmatter, fetch_metadata
except ModuleNotFoundError as _exc:
    if _exc.name != "arxiv_doc_builder":
        raise
    from arxiv_id import safe_arxiv_id, validate_arxiv_id
    from arxiv_metadata import build_frontmatter, fetch_metadata


class AmbiguousMainTexError(Exception):
    """Raised when multiple \\documentclass files exist and no explicit --tex-file was given.

    Selecting the correct entry point cannot be done reliably by heuristics
    (file size, sort order, or trial conversion) because supplements and
    fragments can convert successfully just like the main paper. The caller
    must re-run with --tex-file pointing at the intended file.
    """

    def __init__(self, candidates: list):
        self.candidates = candidates
        super().__init__(f"Found {len(candidates)} files with \\documentclass")


def find_main_tex(source_dir: Path) -> Optional[Path]:
    """Find the main .tex file in source directory.

    Raises AmbiguousMainTexError if multiple files with \\documentclass are
    present and none of the conventional names (main.tex, paper.tex, ms.tex,
    article.tex) exists. The caller is expected to translate this into a
    fail-first error and require --tex-file on the re-run.
    """
    # Conventional main file names take precedence over the ambiguity check:
    # if the source already uses a known layout, there is nothing ambiguous.
    candidates = ["main.tex", "paper.tex", "ms.tex", "article.tex"]

    for candidate in candidates:
        tex_file = source_dir / candidate
        if tex_file.exists():
            return tex_file

    # Collect all .tex files with \documentclass
    doc_files = []
    for tex_file in sorted(source_dir.glob("*.tex")):
        content = tex_file.read_text(encoding="utf-8", errors="ignore")
        if "\\documentclass" in content:
            doc_files.append(tex_file)

    if len(doc_files) == 1:
        return doc_files[0]

    if len(doc_files) > 1:
        raise AmbiguousMainTexError(doc_files)

    return None


def _int_env(name: str, default: int) -> int:
    """Read an int env override, falling back to ``default`` when the var is
    unset, non-numeric, or non-positive. Parsing here (rather than inline at the
    constant) keeps a malformed override — e.g. ``ARXIV_PANDOC_TIMEOUT=3m`` —
    from raising at import time and crashing every command before it starts.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        print(
            f"Ignoring non-integer {name}={raw!r}; using {default}.",
            file=sys.stderr,
        )
        return default
    # Both bounds must be positive: a zero/negative timeout or RSS cap would trip
    # immediately and kill every conversion, so reject those like a parse error.
    if value <= 0:
        print(
            f"Ignoring non-positive {name}={raw!r}; using {default}.",
            file=sys.stderr,
        )
        return default
    return value


# A clean LaTeX->Markdown conversion finishes in seconds even for a 100-page,
# 4000-line paper. When pandoc instead runs unbounded, it is trapped recursively
# expanding a macro it cannot recognize as a no-op — typically a self-referential
# redefinition pulled in from a *bundled style .sty* in the source dir, since
# pandoc reads local .sty files matching a \usepackage. Two observed shapes:
# a CPU spin at flat memory, and a slow leak (~10 MB/s, reaching tens of GB only
# after many minutes). Both are caught by the WALL-CLOCK TIMEOUT, which is the
# only reliable control here — GHC's `+RTS -M` heap cap and a macOS RLIMIT_AS
# were both measured NOT to stop the runaway. The timeout also indirectly bounds
# memory for the slow-leak shape (peak ~= timeout * leak-rate). The RSS WATCHDOG
# is defense-in-depth for a hypothetical fast-allocating runaway the timeout
# alone would not contain in time: it polls real resident memory (immune to the
# RTS/rlimit quirks) and kills early. See SKILL.md "Troubleshooting: Conversion
# Hangs / Runaway Memory". Both bounds are env-overridable for odd edge cases.
PANDOC_TIMEOUT_SECONDS = _int_env("ARXIV_PANDOC_TIMEOUT", 180)
PANDOC_RSS_CAP_MB = _int_env("ARXIV_PANDOC_RSS_CAP_MB", 8192)
_RSS_POLL_SECONDS = 1.0
# Grace to reap the child after SIGKILL before we stop waiting on it; bounding
# this wait keeps a wedged child (e.g. uninterruptible sleep) from re-hanging
# the very call these bounds exist to prevent.
_KILL_REAP_GRACE_SECONDS = 10
# Shared remediation tail for both runaway-kill diagnostics (timeout + memory).
# They describe the same root cause and fix, so the guidance is written once.
_RUNAWAY_REMEDY = (
    "Move the style-only .sty out of the source directory (or comment its "
    "\\usepackage line) and re-run. See SKILL.md 'Troubleshooting: Conversion "
    "Hangs / Runaway Memory'."
)


def _process_rss_mb(pid: int) -> Optional[int]:
    """Resident set size of a pid in MB, or None if it can't be read.

    Shells out to `ps -o rss=` (KB) rather than taking a psutil dependency;
    works on the macOS/Linux targets. RSS (not virtual size) is what causes
    swap thrash, and reading it externally sidesteps the GHC RTS reserving a
    huge virtual address space that defeats RLIMIT_AS-style caps. `ps` is
    resolved to an absolute path so a `.`-in-PATH setup can't run a planted
    binary from the (untrusted) source tree this tool runs subprocesses in.
    """
    ps_bin = shutil.which("ps")
    # shutil.which can return a relative path when PATH holds a relative entry;
    # that would re-resolve against the untrusted cwd, so require an absolute one.
    if ps_bin is None or not os.path.isabs(ps_bin):
        return None
    try:
        out = subprocess.run(
            [ps_bin, "-o", "rss=", "-p", str(pid)],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    out = out.stdout.strip()
    return int(out) // 1024 if out.isdigit() else None


def convert_with_pandoc(
    tex_file: Path,
    output_md: Path,
    timeout: int = PANDOC_TIMEOUT_SECONDS,
    rss_cap_mb: int = PANDOC_RSS_CAP_MB,
) -> bool:
    """Convert LaTeX to Markdown using pandoc, bounded in wall-clock and memory.

    Returns False (with a diagnostic on stderr) instead of hanging when pandoc
    runs away. ``timeout`` is the primary, reliable bound; ``rss_cap_mb`` is a
    secondary watchdog against fast memory growth.
    """
    print(f"Converting {tex_file.name} to Markdown with pandoc...")

    # Resolve pandoc to an absolute path. cwd below is the extracted (untrusted)
    # source tree, so a bare "pandoc" with `.` in PATH could exec a planted
    # binary; an absolute path skips PATH lookup in the child entirely.
    pandoc_bin = shutil.which("pandoc")
    # Require an absolute path: shutil.which can yield a relative one from a
    # relative PATH entry, which would re-resolve against the untrusted cwd.
    if pandoc_bin is None or not os.path.isabs(pandoc_bin):
        print("Error: pandoc not found on PATH as an absolute path.", file=sys.stderr)
        return False

    # Use absolute paths
    tex_file_abs = tex_file.resolve()
    output_md_abs = output_md.resolve()

    # Popen (not subprocess.run) so the loop below can poll RSS while pandoc
    # runs. pandoc writes the document to -o, so stdout stays empty; stderr goes
    # to a temp file rather than a PIPE so it can fill without us draining it —
    # a PIPE left unread during the wait loop could deadlock if pandoc emitted
    # enough to fill the pipe buffer. The temp file is drained once, after exit.
    with tempfile.TemporaryFile() as errf:
        proc = subprocess.Popen(
            [
                pandoc_bin,
                str(tex_file_abs),
                "-f",
                "latex",
                "-t",
                "markdown",
                "--wrap=none",
                "--mathjax",
                "-o",
                str(output_md_abs),
            ],
            stdout=subprocess.DEVNULL,
            stderr=errf,
            cwd=str(tex_file.parent.resolve()),
        )

        start = time.monotonic()
        killed_for = None  # "timeout" | "memory" | None
        while True:
            try:
                proc.wait(timeout=_RSS_POLL_SECONDS)
                break  # finished on its own
            except subprocess.TimeoutExpired:
                pass
            if time.monotonic() - start > timeout:
                killed_for = "timeout"
            else:
                rss = _process_rss_mb(proc.pid)
                if rss is not None and rss > rss_cap_mb:
                    killed_for = "memory"
            if killed_for:
                proc.kill()
                try:
                    proc.wait(timeout=_KILL_REAP_GRACE_SECONDS)
                except subprocess.TimeoutExpired:
                    pass  # reaping shouldn't outlast SIGKILL; never re-hang here
                break

        errf.seek(0)
        stderr = errf.read().decode(errors="replace")

    if killed_for == "timeout":
        # Not "slow" — a runaway. Name the most common root cause and the fix.
        print(
            f"Pandoc did not finish within {timeout}s and was killed. A normal "
            "conversion takes seconds; a runaway almost always means pandoc is "
            "recursively expanding a self-referential macro from a bundled "
            "style .sty in the source directory (pandoc reads local .sty files "
            f"matching a \\usepackage). {_RUNAWAY_REMEDY}",
            file=sys.stderr,
        )
        return False
    if killed_for == "memory":
        print(
            f"Pandoc exceeded the {rss_cap_mb} MB memory watchdog and was "
            "killed (same runaway class as the timeout case — usually a "
            f"self-referential macro from a bundled style .sty). {_RUNAWAY_REMEDY}",
            file=sys.stderr,
        )
        return False
    if proc.returncode != 0:
        print(f"Pandoc conversion failed: {stderr}", file=sys.stderr)
        return False

    print(f"✓ Converted to {output_md}")
    return True


def extract_title_from_latex(tex_file: Path) -> Optional[str]:
    """Extract the paper title from LaTeX source.

    Reads the selected main ``.tex`` first so the fallback title belongs to the
    file actually being converted; only if that file carries no ``\\title`` (it
    may sit in an included preamble) does it scan sibling ``.tex`` files, rather
    than picking an arbitrary file from the directory. Returns ``None`` when no
    ``\\title`` is found, so an unknown title stays null in the frontmatter
    rather than a fabricated placeholder (matching the PDF path).
    """
    candidates = [tex_file]
    candidates += sorted(p for p in tex_file.parent.glob("*.tex") if p != tex_file)
    for candidate in candidates:
        content = candidate.read_text(encoding="utf-8", errors="ignore")
        # Match \title{...} handling nested braces
        match = re.search(r"\\title\s*\{([^{}]*(?:\{[^{}]*\}[^{}]*)*)\}", content)
        if match:
            title = match.group(1)
            # Clean up LaTeX commands
            title = re.sub(r"\\[a-zA-Z]+\s*", "", title)  # Remove commands
            title = re.sub(r"[{}]", "", title)  # Remove braces
            title = re.sub(r"\s+", " ", title).strip()  # Normalize whitespace
            return title or None
    return None


def post_process_markdown(md_file: Path, arxiv_id: str, tex_file: Path):
    """Post-process Markdown for better formatting."""
    from datetime import datetime, timezone

    content = md_file.read_text(encoding="utf-8")

    # A single arXiv fetch supplies the whole provenance frontmatter; the LaTeX
    # \title of the converted file is only a fallback for the title, and only
    # when the arXiv fetch did not provide one (offline / not found). Extracting
    # it lazily avoids a needless file read on the common path. conversion_date
    # is UTC-aware so the provenance stamp is unambiguous across environments.
    meta = fetch_metadata(arxiv_id)
    fallback_title = None
    if meta is None or not meta.title:
        fallback_title = extract_title_from_latex(tex_file)
    header = build_frontmatter(
        meta,
        arxiv_id=arxiv_id,
        source_type="latex",
        conversion_date=datetime.now(timezone.utc).isoformat(),
        fallback_title=fallback_title,
    )

    # Fix figure paths (convert to relative paths)
    content = re.sub(
        r"!\[([^\]]*)\]\(([^)]+)\)",
        lambda m: f"![{m.group(1)}](figures/{Path(m.group(2)).name})",
        content,
    )

    # Clean up excessive blank lines
    content = re.sub(r"\n{3,}", "\n\n", content)

    # Write back
    final_content = header + content
    md_file.write_text(final_content, encoding="utf-8")

    print("✓ Post-processed Markdown")


def copy_figures(source_dir: Path, output_dir: Path):
    """Copy figure files to output directory.

    Only top-level figures are copied. Recursing is tempting but unsafe:
    the markdown post-processor rewrites all image references to
    ``figures/<basename>``, so two nested assets with the same basename
    (e.g. ``main/fig1.png`` and ``supp/fig1.png``) would silently collide
    and substitute the wrong asset for at least one reference. A proper
    fix requires collision-aware, path-preserving copying plus a smarter
    rewriter, which is out of scope here.
    """
    figures_dir = output_dir / "figures"
    figures_dir.mkdir(exist_ok=True)

    # Common image extensions
    image_exts = [".png", ".jpg", ".jpeg", ".pdf", ".eps"]

    copied = 0
    for ext in image_exts:
        for img_file in source_dir.glob(f"*{ext}"):
            dest = figures_dir / img_file.name
            dest.write_bytes(img_file.read_bytes())
            copied += 1

    if copied > 0:
        print(f"✓ Copied {copied} figure(s) to {figures_dir}")


def main():
    parser = argparse.ArgumentParser(description="Convert LaTeX to Markdown")
    parser.add_argument("arxiv_id", help="arXiv ID")
    parser.add_argument(
        "--source-dir",
        type=Path,
        help="LaTeX source directory (default: papers/ARXIV_ID/source)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output Markdown file (default: papers/ARXIV_ID/ARXIV_ID.md)",
    )
    parser.add_argument(
        "--tex-file",
        type=Path,
        help="Specify the main .tex file directly (overrides auto-detection)",
    )

    args = parser.parse_args()

    try:
        validate_arxiv_id(args.arxiv_id)
    except ValueError as e:
        # Exit 1 (generic failure). Exit 2 is reserved below for the
        # "ambiguous main .tex" signal, which callers distinguish from
        # generic failures.
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    # Run safe_arxiv_id through the default paths so legacy IDs like
    # "hep-th/9901001" don't smuggle a slash into the directory / filename
    # (which would produce papers/hep-th/9901001/... and mismatch the
    # fetch-side cache at papers/hep-th_9901001/).
    safe_id = safe_arxiv_id(args.arxiv_id)

    if args.source_dir:
        source_dir = args.source_dir
    else:
        source_dir = Path("papers") / safe_id / "source"

    if args.output:
        output_md = args.output
    else:
        output_md = Path("papers") / safe_id / f"{safe_id}.md"

    # Check source directory exists
    if not source_dir.exists():
        print(f"Error: Source directory not found: {source_dir}")
        sys.exit(1)

    # Find main .tex file
    if args.tex_file:
        tex_file = args.tex_file
        if not tex_file.exists():
            print(f"Error: Specified .tex file not found: {tex_file}")
            sys.exit(1)
    else:
        try:
            tex_file = find_main_tex(source_dir)
        except AmbiguousMainTexError as e:
            # Fail-first: do not guess. Require an explicit --tex-file on re-run.
            # Use absolute paths so the suggestion is portable across cwd and
            # --output-dir differences between the original run and the re-run.
            abs_candidates = [c.resolve() for c in e.candidates]
            print(
                f"Error: Found {len(abs_candidates)} files with \\documentclass "
                f"in {source_dir.resolve()}:",
                file=sys.stderr,
            )
            for c in abs_candidates:
                print(f"  - {c}", file=sys.stderr)
            print(
                "\nMain .tex selection is ambiguous. Re-run with --tex-file "
                "pointing at the correct file, e.g.:",
                file=sys.stderr,
            )
            print(
                f"  convert-paper <ARXIV_ID> --tex-file {abs_candidates[0]}",
                file=sys.stderr,
            )
            print(
                "\nIf you originally passed --output-dir, include the same value "
                "in the re-run.",
                file=sys.stderr,
            )
            sys.exit(2)
    if not tex_file:
        print(f"Error: No main .tex file found in {source_dir}")
        sys.exit(1)

    print(f"Found main file: {tex_file.name}")

    # Check pandoc is available
    result = subprocess.run(["which", "pandoc"], capture_output=True)
    if result.returncode != 0:
        print("Error: pandoc not found. Install with: brew install pandoc")
        sys.exit(1)

    # Convert
    output_md.parent.mkdir(parents=True, exist_ok=True)
    if not convert_with_pandoc(tex_file, output_md):
        sys.exit(1)

    # Post-process
    post_process_markdown(output_md, args.arxiv_id, tex_file)

    # Copy figures
    copy_figures(source_dir, output_md.parent)

    print()
    print("=" * 50)
    print(f"✓ Conversion complete: {output_md}")


if __name__ == "__main__":
    main()
