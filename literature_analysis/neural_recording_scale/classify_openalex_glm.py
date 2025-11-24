"""
Classify OpenAlex metadata rows with Grok via OpenRouter.

Reads a JSONL from the OpenAlex pull (default: data/openalex_biorxiv_neuro_<date>.jsonl),
reconstructs abstracts, and sends them to x-ai/grok-4.1-fast:free for triage.

Outputs JSONL with model verdicts and bookkeeping.

Usage:
  OPENROUTER_API_KEY=... python classify_openalex_grok.py \
      --input data/openalex_biorxiv_neuro_2025-11-24.jsonl \
      --output data/openalex_grok_labels_2025-11-24.jsonl \
      --max 100 --batch-size 10
"""

from __future__ import annotations

import argparse
import json
import math
import os
import threading
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Dict, List, Optional

import requests
from tqdm import tqdm


# Default model: GLM 4.5 Air free endpoint via OpenRouter
DEFAULT_MODEL = "z-ai/glm-4.5-air:free"
SYSTEM_PROMPT = (
    "You are an expert neural recording methods curator. "
    "Respond ONLY with JSON exactly as requested. No commentary."
)

USER_TEMPLATE = """You will receive a batch of paper metadata (id, title, first author, year, abstract).
For each paper, decide if the full paper likely contains useful information about state-of-the-art neural recording methods.
Focus ONLY on invasive methods: penetrating electrodes, ECoG arrays, calcium or voltage imaging (including miniscope/mesoscope/two-photon/three-photon/light-sheet), functional ultrasound (typically requires craniotomy). Ignore non-invasive EEG/MEG/fMRI unless clearly paired with invasive recordings.

Promising criteria (any of these counts):
1) Methods development enabling large-scale recordings (new hardware/indicators/arrays/optics/fUS pipeline).
2) Evidence of large or “massive” datasets.
3) Study only feasible with large datasets.
4) Mentions of advances in: dataset size; number of probes; neurons per session; % of brain recorded (whole-brain).
5) Clearly demonstrates unusually large-scale invasive recordings (e.g., many probes, thousands of neurons, or near whole-brain coverage) even if using existing technologies, including cases where the abstract explicitly uses phrases like “large-scale recording” or similar even without giving exact numbers or hardware details.

If unclear, err on the side of NOT promising.

For each paper, return an object with:
- id: the input id
- summary: one-line reason (from abstract) why it is or is not promising
- promising: true/false
- paper_type: methods | results | review | opinion | other | "N/A"
- species: human | macaque | tree shrew | rat | mouse | zebrafish | drosophila | C Elegans | multiple | other | "N/A"
- technology: specific neural recording method; "N/A" if not stated
- yield: number of neurons per session if available; else "N/A"
- chronic: true/false if the technology is meant for chronic implantation; "N/A" if unknown

Always include all fields above. Use "N/A" when a field is not inferable from the abstract. Do not invent numbers.

Return a JSON array (no prose) where each element corresponds to one input paper, in the same order.

INPUT PAPERS:
{items}
"""


def reconstruct_abstract(inv: Dict[str, List[int]]) -> str:
    """Rebuild abstract from OpenAlex inverted index."""
    if not inv:
        return ""
    max_pos = max(pos for positions in inv.values() for pos in positions)
    words = [""] * (max_pos + 1)
    for word, positions in inv.items():
        for pos in positions:
            words[pos] = word
    return " ".join(words)


def call_openrouter(api_key: str, prompt: str, model: str) -> str:
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "HTTP-Referer": "https://github.com/NZ99/neural_recordings",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "text"},
    }
    # Attach model-specific reasoning config when supported.
    # Note: OpenRouter may ignore reasoning for some "non-reasoning" free endpoints.
    if model.startswith("x-ai/grok-4.1"):
        payload["reasoning"] = {"effort": "medium"}
    elif "glm-4.5" in model:
        # GLM-4.5-Air supports a boolean reasoning flag in its own API;
        # OpenRouter may or may not honor this on the free endpoint.
        payload["reasoning"] = {"enabled": True}
    resp = requests.post(url, headers=headers, json=payload, timeout=120)
    if resp.status_code == 429:
        time.sleep(5)
        resp = requests.post(url, headers=headers, json=payload, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def parse_model_json(text: str) -> Optional[list]:
    """Extract JSON array from model output."""
    text = text.strip()
    try:
        obj = json.loads(text)
        if isinstance(obj, list):
            return obj
    except Exception:
        pass
    start = text.find("[")
    end = text.rfind("]")
    if start != -1 and end != -1 and end > start:
        try:
            obj = json.loads(text[start : end + 1])
            if isinstance(obj, list):
                return obj
        except Exception:
            return None
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True, help="Input OpenAlex JSONL")
    parser.add_argument("--output", type=Path, required=True, help="Output JSONL of classifications")
    parser.add_argument("--max", type=int, default=None, help="Limit number of records")
    parser.add_argument("--start", type=int, default=0, help="Skip first N records")
    parser.add_argument("--batch-size", type=int, default=10, help="Number of papers per API call")
    parser.add_argument("--concurrency", type=int, default=10, help="Parallel API calls")
    parser.add_argument("--calls-per-minute", type=int, default=15, help="Throttle to this many calls/minute (safety below OpenRouter 20)")
    parser.add_argument("--daily-call-cap", type=int, default=1000, help="Abort if planned calls exceed this cap")
    parser.add_argument("--max-retries", type=int, default=3, help="Retries per batch on API/parse failure")
    parser.add_argument("--resume", action="store_true", help="Append to existing output and skip already-processed batches")
    parser.add_argument("--model", type=str, default=DEFAULT_MODEL, help="OpenRouter model slug (e.g. z-ai/glm-4.5-air:free or x-ai/grok-4.1-fast:free)")
    args = parser.parse_args()

    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise SystemExit("Set OPENROUTER_API_KEY")

    model = args.model

    with args.input.open() as fp:
        lines = fp.readlines()

    if args.start:
        lines = lines[args.start :]
    if args.max:
        lines = lines[: args.max]

    # Load already processed ids if resuming
    processed_ids = set()
    processed_batches = 0
    if args.resume and args.output.exists():
        with args.output.open() as fp:
            for line in fp:
                try:
                    obj = json.loads(line)
                    processed_batches += 1
                    for pid in obj.get("input_ids", []):
                        processed_ids.add(pid)
                except Exception:
                    continue

    # Build batches
    batches = []
    for i in range(0, len(lines), args.batch_size):
        batch_lines = lines[i : i + args.batch_size]
        batch = []
        for line in batch_lines:
            obj = json.loads(line)
            abstract = reconstruct_abstract(obj.get("abstract_inverted_index"))
            title = obj.get("title", "")
            authors = obj.get("authorships") or []
            first_author = authors[0].get("author", {}).get("display_name", "") if authors else ""
            pub_year = obj.get("publication_year") or obj.get("year") or "N/A"
            batch.append(
                {
                    "id": obj.get("id"),
                    "title": title,
                    "first_author": first_author,
                    "year": pub_year,
                    "abstract": abstract,
                }
            )
        batches.append((i + args.start, batch))

    # Skip batches fully processed if resuming
    if processed_ids:
        batches = [
            (idx, batch)
            for idx, batch in batches
            if not all(b["id"] in processed_ids for b in batch)
        ]

    planned_calls = len(batches)
    if planned_calls > args.daily_call_cap:
        raise SystemExit(f"Planned calls {planned_calls} exceed daily_call_cap={args.daily_call_cap}. Reduce --max or increase cap deliberately.")

    # Rate limiter (token bucket with timestamps)
    limiter_lock = threading.Lock()
    call_timestamps = deque()

    def wait_for_slot():
        while True:
            with limiter_lock:
                now = time.time()
                # drop timestamps older than 60s
                while call_timestamps and now - call_timestamps[0] > 60:
                    call_timestamps.popleft()
                if len(call_timestamps) < args.calls_per_minute:
                    call_timestamps.append(now)
                    return
            time.sleep(0.2)

    out_mode = "a" if args.resume else "w"
    out_f = args.output.open(out_mode)
    write_lock = threading.Lock()
    total_inputs = 0

    def process_batch(batch_start_index: int, batch_data: List[Dict[str, str]]):
        items_text = "\n\n".join(
            [
                f"- id: {b['id']}\n  title: {b['title']}\n  first_author: {b['first_author']}\n  year: {b['year']}\n  abstract: {b['abstract']}"
                for b in batch_data
            ]
        )
        prompt = USER_TEMPLATE.format(items=items_text)

        response_text = None
        parsed = None
        error_msg = None

        for attempt in range(1, args.max_retries + 1):
            wait_for_slot()
            try:
                response_text = call_openrouter(api_key, prompt, model)
                parsed = parse_model_json(response_text)
                if parsed is not None:
                    break  # success
                else:
                    error_msg = "parse_error"
            except Exception as e:
                error_msg = f"exception: {e}"
            # backoff a bit before retrying
            time.sleep(1 + attempt)

        if parsed is None and error_msg:
            response_text = response_text or error_msg

        record = {
            "batch_start_index": batch_start_index,
            "input_ids": [b["id"] for b in batch_data],
            "model_raw": response_text,
            "model_parsed": parsed,
        }
        with write_lock:
            out_f.write(json.dumps(record))
            out_f.write("\n")
            out_f.flush()
        return len(batch_data)

    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(process_batch, idx, batch) for idx, batch in batches]
        for fut in tqdm(as_completed(futures), total=len(futures), desc="Batches done", unit="batch"):
            total_inputs += fut.result()

    out_f.close()
    print(f"Wrote {total_inputs} input papers across {len(batches)} batches to {args.output}")


if __name__ == "__main__":
    main()
