#!/usr/bin/env python3
"""
Fetch arXiv paper materials (source and/or PDF).

Tries to fetch LaTeX source first, falls back to PDF if unavailable.
"""

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

# Importable both as a package member (pytest / entry point) and as a
# bare script launched via subprocess from convert_paper.py. Narrow to
# ModuleNotFoundError + name check so that an ImportError raised *inside*
# arxiv_id.py (transitive missing dep, partial load) is not masked by the
# fallback — only a genuinely absent top-level package falls through.
try:
    from arxiv_doc_builder.arxiv_id import safe_arxiv_id, validate_arxiv_id
    from arxiv_doc_builder.arxiv_metadata import MetadataFetch, fetch_metadata
except ModuleNotFoundError as _exc:
    if _exc.name != "arxiv_doc_builder":
        raise
    # Script invocation: script dir is on sys.path[0], so arxiv_id.py is
    # importable as a top-level module.
    from arxiv_id import safe_arxiv_id, validate_arxiv_id
    from arxiv_metadata import MetadataFetch, fetch_metadata


_METADATA_FILE = ".arxiv-fetch.json"


def _probe_metadata(arxiv_id: str) -> MetadataFetch:
    """Query the arXiv API for the record the drift check reads.

    Returns the whole outcome, not just a version string. An unreachable API
    and a record without a version tail both leave the sidecar unwritten, and
    only the outcome tells them apart.

    Delegates to ``fetch_metadata`` for the Atom request. ``_latest_version``
    reads the version out. A short timeout keeps the pre-fetch probe light.

    Assumes ``arxiv_id`` has already been validated to canonical form by
    ``validate_arxiv_id``. No zero-padding happens here.
    """
    return fetch_metadata(arxiv_id, timeout=5)


def _latest_version(probe: MetadataFetch) -> Optional[str]:
    """The version string the probe reports, or ``None`` when it reports none.

    The rest of this module reads ``None`` as "no usable answer from the API",
    whether the request failed or the record carried no version tail.
    """
    return probe.metadata.version if probe.metadata else None


def _read_cached_version(paper_dir: Path) -> Optional[str]:
    """Read the previously recorded arXiv version, or None."""
    meta = paper_dir / _METADATA_FILE
    if not meta.exists():
        return None
    try:
        data = json.loads(meta.read_text(encoding="utf-8"))
        return data.get("version")
    except Exception:
        return None


def _record_version(paper_dir: Path, latest: Optional[str], *, fetched: bool) -> bool:
    """Persist the fetched version, reporting whether it was persisted.

    Writes only with a version *and* material. Recording a version for an empty
    paper directory would misrepresent it. Returns ``False`` having written
    nothing otherwise.
    """
    if latest is None or not fetched:
        return False
    _write_cached_version(paper_dir, latest)
    return True


def _format_sidecar_skip_warning(arxiv_id: str, probe: MetadataFetch) -> str:
    """The warning for a run that fetched material but recorded no version.

    Composed here, not through the conversion paths' shared warning. This step
    writes no frontmatter and has no null fields to explain, and it fires on a
    probe that may have succeeded.

    Call only when ``_record_version`` returned ``False`` for a run that did
    obtain material.
    """
    if _latest_version(probe) is not None:
        raise ValueError(
            "the probe reported a version, so the sidecar was not skipped for "
            "the reason this warning states"
        )
    if probe.error is not None:
        situation = f"could not read the arXiv record for {arxiv_id}: {probe.error}"
    else:
        situation = f"the arXiv record for {arxiv_id} carried no version"
    return (
        f"WARNING: {situation}\n"
        f"  Version drift was not checked, and {_METADATA_FILE} was not updated."
    )


def _write_cached_version(paper_dir: Path, version: str) -> None:
    """Record the fetched arXiv version."""
    meta = paper_dir / _METADATA_FILE
    meta.write_text(
        json.dumps({"version": version}, ensure_ascii=False),
        encoding="utf-8",
    )


def _detect_file_type(path: Path) -> str:
    """Detect downloaded file type using the file command.

    arXiv source downloads come in several formats:
      - gzip-compressed tar archive (most common for multi-file submissions)
      - gzip-compressed single .tex file (common for older papers)
      - plain text .tex file (rare)

    The file command on the outer gzip layer cannot distinguish between a
    tar archive and a single file inside, so for gzip files we decompress
    and check the inner content.

    Returns one of: "tar", "gzip_single", "latex", "unknown"
    """
    result = subprocess.run(
        ["file", "--brief", str(path)], capture_output=True, text=True
    )
    desc = result.stdout.strip().lower()

    if "tar archive" in desc:
        return "tar"

    if "gzip" in desc:
        # Decompress and check the inner content type via pipe
        inner = subprocess.run(
            f'gunzip -c "{path}" | file --brief -',
            shell=True,
            capture_output=True,
            text=True,
        )
        inner_desc = inner.stdout.strip().lower()
        if "tar archive" in inner_desc:
            return "tar"
        # Single file (LaTeX, text, etc.)
        return "gzip_single"

    if "latex" in desc or "tex" in desc or "ascii text" in desc:
        return "latex"
    return "unknown"


def _extract_gzip_single(downloaded: Path, source_dir: Path) -> bool:
    """Extract a single gzip-compressed file (not a tar archive).

    The file command output often contains the original filename, e.g.:
      "gzip compressed data, was \"main.tex\", ..."
    We use that to name the output file, falling back to main.tex.
    """
    # Try to recover the original filename from gzip metadata
    result = subprocess.run(
        ["file", "--brief", str(downloaded)], capture_output=True, text=True
    )
    desc = result.stdout.strip()

    original_name = "main.tex"
    if 'was "' in desc:
        # Extract name between quotes: was "foo.tex"
        start = desc.index('was "') + 5
        end = desc.index('"', start)
        original_name = desc[start:end]

    source_dir.mkdir(exist_ok=True)
    out_path = source_dir / original_name

    decompress = subprocess.run(["gunzip", "-c", str(downloaded)], capture_output=True)
    if decompress.returncode != 0:
        print(f"Failed to decompress: {decompress.stderr.decode()}")
        return False

    out_path.write_bytes(decompress.stdout)
    print(f"✓ Source extracted to {out_path} (single gzip file)")
    return True


def _needs_refresh(paper_dir: Path, latest: Optional[str]) -> bool:
    """Decide whether cached artifacts should be re-fetched.

    Returns True when the arXiv API reports a newer version than what
    is recorded locally. Returns False (trust cache) when the API is
    unreachable or the versions match.
    """
    if latest is None:
        return False
    cached = _read_cached_version(paper_dir)
    if cached is None:
        # No metadata — either a pre-metadata cache or first run.
        # Re-fetch to establish a version record.
        return True
    return cached != latest


def fetch_source(
    arxiv_id: str,
    output_dir: Path,
    file_id: str,
    *,
    refresh: bool = False,
) -> bool:
    """
    Fetch LaTeX source from arXiv.

    Handles three arXiv source formats:
      - tar.gz archive (most common)
      - single gzip-compressed .tex file (common for older papers)
      - plain text .tex file (rare)

    Idempotent: if the source directory already contains at least one
    ``.tex`` file, the network fetch is skipped — unless ``refresh``
    is True (version drift detected).

    Returns:
        True if source is available (freshly fetched or already present),
        False if the fetch failed or the source is not available on arXiv.
    """
    source_url = f"https://arxiv.org/src/{arxiv_id}"
    downloaded = output_dir / f"{file_id}-src.tar.gz"
    source_dir = output_dir / "source"

    if source_dir.exists() and any(source_dir.rglob("*.tex")) and not refresh:
        print(f"✓ Source already present at {source_dir}, skipping fetch")
        return True

    if refresh:
        # Clear stale source tree so renamed/deleted files don't persist
        shutil.rmtree(source_dir, ignore_errors=True)

    print(f"Fetching source from {source_url}...")

    result = subprocess.run(
        ["curl", "-f", "-L", "-o", str(downloaded), source_url], capture_output=True
    )

    if result.returncode != 0:
        print("Source not available (paper may be PDF-only)")
        downloaded.unlink(missing_ok=True)
        return False

    # Detect file type and extract accordingly
    file_type = _detect_file_type(downloaded)
    print(f"  Detected source format: {file_type}")

    extract_ok = False
    if file_type == "tar":
        source_dir.mkdir(exist_ok=True)
        result = subprocess.run(
            ["tar", "-xzf", str(downloaded), "-C", str(source_dir)], capture_output=True
        )
        if result.returncode != 0:
            print(f"Failed to extract source: {result.stderr.decode()}")
        else:
            print(f"✓ Source extracted to {source_dir}")
            extract_ok = True

    elif file_type == "gzip_single":
        extract_ok = _extract_gzip_single(downloaded, source_dir)

    elif file_type == "latex":
        # Plain uncompressed .tex file
        source_dir.mkdir(exist_ok=True)
        dest = source_dir / "main.tex"
        dest.write_bytes(downloaded.read_bytes())
        print(f"✓ Source saved to {dest} (uncompressed)")
        extract_ok = True

    else:
        print(f"Unknown source format: {file_type}")

    if not extract_ok:
        # Remove partial extraction so it cannot masquerade as a cache hit
        shutil.rmtree(source_dir, ignore_errors=True)
        downloaded.unlink(missing_ok=True)
        return False

    downloaded.unlink()  # Clean up downloaded file
    return True


def fetch_pdf(
    arxiv_id: str,
    output_dir: Path,
    file_id: str,
    *,
    refresh: bool = False,
) -> bool:
    """
    Fetch PDF from arXiv.

    Idempotent: if the PDF file already exists and is non-empty, the
    network fetch is skipped — unless ``refresh`` is True (version
    drift detected).

    Returns:
        True if PDF is available (freshly fetched or already present),
        False if the fetch failed.
    """
    pdf_url = f"https://arxiv.org/pdf/{arxiv_id}.pdf"
    pdf_dir = output_dir / "pdf"
    pdf_file = pdf_dir / f"{file_id}.pdf"

    if pdf_file.exists() and pdf_file.stat().st_size > 0 and not refresh:
        print(f"✓ PDF already present at {pdf_file}, skipping fetch")
        return True

    print(f"Fetching PDF from {pdf_url}...")

    pdf_dir.mkdir(exist_ok=True)
    result = subprocess.run(
        ["curl", "-f", "-L", "-o", str(pdf_file), pdf_url], capture_output=True
    )

    if result.returncode != 0:
        print(f"Failed to fetch PDF: {result.stderr.decode()}")
        pdf_file.unlink(missing_ok=True)
        return False

    if pdf_file.stat().st_size == 0:
        print("Failed to fetch PDF: empty response")
        pdf_file.unlink(missing_ok=True)
        return False

    print(f"✓ PDF saved to {pdf_file}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Fetch arXiv paper materials")
    parser.add_argument("arxiv_id", help="arXiv ID (e.g., 2409.03108)")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("papers"),
        help="Output directory (default: ./papers)",
    )
    args = parser.parse_args()

    try:
        validate_arxiv_id(args.arxiv_id)
    except ValueError as e:
        # Exit 1 (generic failure) rather than 2: exit 2 is reserved for
        # "ambiguous main .tex" per convert_paper.py's child-propagation
        # contract, and wrappers that retry on 2 with --tex-file would
        # otherwise misinterpret an ID typo as a source-selection problem.
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    normalized_arxiv_id = safe_arxiv_id(args.arxiv_id)

    # Create paper directory
    paper_dir = args.output_dir / normalized_arxiv_id
    paper_dir.mkdir(parents=True, exist_ok=True)

    print(f"Fetching materials for arXiv:{args.arxiv_id}")
    print(f"Output directory: {paper_dir}")
    print()

    # Check for version drift before fetching
    probe = _probe_metadata(args.arxiv_id)
    latest = _latest_version(probe)
    refresh = _needs_refresh(paper_dir, latest)
    if refresh:
        cached = _read_cached_version(paper_dir)
        if cached is None:
            print(
                f"No version metadata found, re-fetching to establish record (latest={latest})"
            )
        else:
            print(f"⚠ Version drift detected: cached={cached}, latest={latest}")
        print()

    has_source = fetch_source(
        args.arxiv_id,
        paper_dir,
        normalized_arxiv_id,
        refresh=refresh,
    )
    has_pdf = fetch_pdf(
        args.arxiv_id,
        paper_dir,
        normalized_arxiv_id,
        refresh=refresh,
    )

    # Record version after successful fetch
    fetched_any = has_source or has_pdf
    if not _record_version(paper_dir, latest, fetched=fetched_any) and fetched_any:
        print(_format_sidecar_skip_warning(args.arxiv_id, probe), file=sys.stderr)

    # Summary
    print()
    print("=" * 50)
    if has_source:
        print("✓ LaTeX source available")
    if has_pdf:
        print("✓ PDF available")

    if not fetched_any:
        print("✗ Failed to fetch any materials")
        sys.exit(1)

    print(f"\nMaterials saved to: {paper_dir}")


if __name__ == "__main__":
    main()
