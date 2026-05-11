#!/usr/bin/env python3
"""
Download arXiv PDFs and LaTeX source archives from candidate metadata.

Input:
  paper_collection/metadata/arxiv_candidates.jsonl

Output:
  paper_collection/pdf/<arxiv_id>.pdf
  paper_collection/source/<arxiv_id>.<ext>
  paper_collection/metadata/download_manifest.jsonl
"""

from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError


DEFAULT_INPUT = Path("paper_collection/metadata/arxiv_candidates.jsonl")
DEFAULT_OUTPUT_ROOT = Path("paper_collection")


def safe_id(arxiv_id: str) -> str:
    return arxiv_id.replace("/", "_")


def load_papers(path: Path) -> list[dict]:
    papers: list[dict] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                papers.append(json.loads(line))
    return papers


def guess_source_suffix(content_type: str, fallback_url: str) -> str:
    lowered = content_type.lower()
    if "gzip" in lowered or "tar" in lowered:
        return ".tar.gz"
    if "pdf" in lowered:
        return ".pdf"
    if fallback_url.endswith(".gz"):
        return ".tar.gz"
    return ".src"


def download_file(
    url: str,
    output_path: Path,
    timeout: int,
    retries: int,
    retry_delay_seconds: float,
) -> dict:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_size > 0:
        return {
            "status": "skipped_existing",
            "path": str(output_path),
            "bytes": output_path.stat().st_size,
            "content_type": "",
        }

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "master-nctq-arxiv-download/0.1 (research dataset collection)"},
    )

    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                content = response.read()
                content_type = response.headers.get("Content-Type", "")
                output_path.write_bytes(content)
                return {
                    "status": "downloaded",
                    "path": str(output_path),
                    "bytes": len(content),
                    "content_type": content_type,
                }
        except HTTPError as error:
            if error.code == 404:
                return {
                    "status": "not_found",
                    "path": str(output_path),
                    "bytes": 0,
                    "content_type": "",
                    "error": str(error),
                }
            if error.code != 429 or attempt == retries:
                return {
                    "status": "error",
                    "path": str(output_path),
                    "bytes": 0,
                    "content_type": "",
                    "error": str(error),
                }
        except URLError as error:
            if attempt == retries:
                return {
                    "status": "error",
                    "path": str(output_path),
                    "bytes": 0,
                    "content_type": "",
                    "error": str(error),
                }

        wait_seconds = retry_delay_seconds * (attempt + 1)
        print(f"Retrying {url} in {wait_seconds:.1f}s...")
        time.sleep(wait_seconds)

    return {
        "status": "error",
        "path": str(output_path),
        "bytes": 0,
        "content_type": "",
        "error": "unexpected download failure",
    }


def download_papers(
    papers: list[dict],
    output_root: Path,
    limit: int | None,
    include_source: bool,
    timeout: int,
    retries: int,
    retry_delay_seconds: float,
    delay_seconds: float,
) -> list[dict]:
    selected = papers[:limit] if limit is not None else papers
    manifest: list[dict] = []

    for index, paper in enumerate(selected, start=1):
        arxiv_id = paper["arxiv_id"]
        base_name = safe_id(arxiv_id)
        print(f"[{index}/{len(selected)}] {arxiv_id} - {paper['title'][:80]}")

        pdf_result = download_file(
            url=paper["pdf_url"],
            output_path=output_root / "pdf" / f"{base_name}.pdf",
            timeout=timeout,
            retries=retries,
            retry_delay_seconds=retry_delay_seconds,
        )

        source_result = None
        if include_source:
            source_url = paper["source_url"]
            temp_source_path = output_root / "source" / f"{base_name}.src"
            source_result = download_file(
                url=source_url,
                output_path=temp_source_path,
                timeout=timeout,
                retries=retries,
                retry_delay_seconds=retry_delay_seconds,
            )
            if source_result["status"] == "downloaded":
                suffix = guess_source_suffix(source_result["content_type"], source_url)
                final_path = output_root / "source" / f"{base_name}{suffix}"
                if final_path != temp_source_path:
                    temp_source_path.replace(final_path)
                    source_result["path"] = str(final_path)

        manifest.append(
            {
                "arxiv_id": arxiv_id,
                "title": paper["title"],
                "pdf": pdf_result,
                "source": source_result,
            }
        )
        time.sleep(delay_seconds)

    return manifest


def write_manifest(manifest: list[dict], output_root: Path) -> Path:
    output_path = output_root / "metadata" / "download_manifest.jsonl"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as file:
        for row in manifest:
            file.write(json.dumps(row, ensure_ascii=False) + "\n")
    return output_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download PDFs and source archives for arXiv papers.")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--no-source", action="store_true", help="Only download PDFs.")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--retries", type=int, default=2)
    parser.add_argument("--retry-delay-seconds", type=float, default=15.0)
    parser.add_argument("--delay-seconds", type=float, default=3.0)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    papers = load_papers(args.input)
    manifest = download_papers(
        papers=papers,
        output_root=args.output_root,
        limit=args.limit,
        include_source=not args.no_source,
        timeout=args.timeout,
        retries=args.retries,
        retry_delay_seconds=args.retry_delay_seconds,
        delay_seconds=args.delay_seconds,
    )
    manifest_path = write_manifest(manifest, args.output_root)
    downloaded_pdf = sum(1 for row in manifest if row["pdf"]["status"] in {"downloaded", "skipped_existing"})
    downloaded_source = sum(
        1
        for row in manifest
        if row["source"] and row["source"]["status"] in {"downloaded", "skipped_existing"}
    )
    print(f"Wrote manifest to {manifest_path}")
    print(f"PDF available: {downloaded_pdf}/{len(manifest)}")
    print(f"Source available: {downloaded_source}/{len(manifest)}")


if __name__ == "__main__":
    main()
