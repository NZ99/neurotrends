"""
Query OpenAlex for neural recording papers using an "Andrew White" API-first approach.

- Uses OpenAlex search (no local dumps).
- Broad recording keywords (ephys + optical), no neuron-term gate.
- Saves JSONL metadata to data/openalex_single_neuron_<YYYY-MM-DD>.jsonl.
"""

from __future__ import annotations

import json
import os
import time
from datetime import date
from pathlib import Path
from typing import Iterable, Optional, Set

import requests

# OpenAlex identifiers
BIO_RXIV_SOURCE_ID = "https://openalex.org/S4306402567"  # bioRxiv
NEUROSCIENCE_CONCEPT_ID = "https://openalex.org/C169760540"  # Neuroscience concept (level 1)

# Recording-related keywords (kept compact to stay under URL limits)
RECORDING_TERMS = [
    # generic ephys
    "electrophysiolog*",
    # specific ephys methods / hardware
    "single unit",
    "multiunit",
    "spike train",
    "extracellular recording",
    "intracellular recording",
    "patch clamp",
    "microelectrode array",
    "multi electrode array",
    "Neuropixels",
    # optical calcium / voltage
    "calcium imaging",
    "two photon",
    "three photon",
    "light sheet",
    "miniscope",
    "mesoscope",
    "voltage imaging",
    "GCaMP",
    "GEVI",
]


def _quote(term: str) -> str:
    """Quote multi-word terms for OpenAlex search."""
    if " " in term:
        return f'"{term}"'
    return term


def build_search_query(terms: Iterable[str]) -> str:
    """OR-join terms for OpenAlex's `search` parameter."""
    return " OR ".join(_quote(t) for t in terms)


def fetch_openalex(
    query: str,
    start_date: str = "2021-01-01",
    per_page: int = 200,
    max_results: Optional[int] = None,
    source_id: Optional[str] = None,
    concept_id: Optional[str] = None,
    sleep_on_rate_limit: int = 10,
) -> Iterable[dict]:
    """
    Stream results from OpenAlex matching the query.

    Args:
        query: OpenAlex search string.
        start_date: inclusive publication date filter (YYYY-MM-DD).
        per_page: page size (max 200).
        max_results: optional cap to avoid runaway downloads.
        source_id: optional OpenAlex source id to restrict (e.g., bioRxiv).
        concept_id: optional OpenAlex concept id to restrict (e.g., Neuroscience).
        sleep_on_rate_limit: seconds to sleep when hitting 429.
    """
    url = "https://api.openalex.org/works"
    cursor = "*"
    fetched = 0

    while cursor:
        filters = [f"from_publication_date:{start_date}"]
        if source_id:
            filters.append(f"primary_location.source.id:{source_id}")
        if concept_id:
            filters.append(f"concept.id:{concept_id}")

        params = {
            "search": query,
            "filter": ",".join(filters),
            "per-page": per_page,
            "cursor": cursor,
            "sort": "publication_date:desc",
        }
        resp = requests.get(url, params=params, timeout=60)

        if resp.status_code == 429:
            time.sleep(sleep_on_rate_limit)
            continue
        resp.raise_for_status()

        payload = resp.json()
        results = payload.get("results", [])
        for item in results:
            yield item
            fetched += 1
            if max_results and fetched >= max_results:
                return

        cursor = payload.get("meta", {}).get("next_cursor")
        if not cursor:
            break


def save_jsonl(path: Path, items: Iterable[dict]) -> int:
    """Write iterable of dicts to JSONL, return count."""
    count = 0
    with path.open("w") as fp:
        for obj in items:
            fp.write(json.dumps(obj))
            fp.write("\n")
            count += 1
    return count


def main():
    data_dir = Path("data")
    data_dir.mkdir(parents=True, exist_ok=True)

    today = date.today().isoformat()
    out_file = data_dir / f"openalex_biorxiv_neuro_{today}.jsonl"

    search_query = build_search_query(RECORDING_TERMS)
    print(f"Querying OpenAlex with:\n  {search_query}")
    print(
        "Filters: from_publication_date >= 2021-01-01; "
        f"source={BIO_RXIV_SOURCE_ID}; concept={NEUROSCIENCE_CONCEPT_ID}"
    )

    seen: Set[str] = set()

    def unique_items():
        for item in fetch_openalex(
            search_query,
            source_id=BIO_RXIV_SOURCE_ID,
            concept_id=NEUROSCIENCE_CONCEPT_ID,
        ):
            work_id = item.get("id")
            if work_id in seen:
                continue
            seen.add(work_id)
            yield item

    count = save_jsonl(out_file, unique_items())
    size_mb = out_file.stat().st_size / 1e6 if out_file.exists() else 0
    print(f"Saved {count} records to {out_file} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
