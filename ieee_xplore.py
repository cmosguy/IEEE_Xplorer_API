#!/usr/bin/env python3
"""
ieee_xplore.py - Query the IEEE Xplore REST API and export results to CSV.

Usage:
    python ieee_xplore.py --api-key-file /path/to/key.txt
    python ieee_xplore.py --api-key-file /path/to/key.txt --query "haptics AND wearable"
    python ieee_xplore.py --api-key-file /path/to/key.txt --validate
    IEEE_API_KEY_FILE=/path/to/key.txt python ieee_xplore.py

Dependencies: requests  (pip install -r requirements.txt)
"""

import argparse
import csv
import os
import sys
import time

import requests

BASE_URL = "https://ieeexploreapi.ieee.org/api/v1/search/articles"


def read_api_key(path: str) -> str:
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read().strip()
    except FileNotFoundError:
        sys.exit(f"Error: API key file not found: {path}")
    except OSError as exc:
        sys.exit(f"Error reading API key file: {exc}")


def validate_api_key(api_key: str) -> None:
    # Minimal search to validate the key — consumes 1 of your 200 daily calls.
    params = {
        "apikey": api_key,
        "max_records": 1,
        "article_number": 1,
    }
    try:
        response = requests.get(BASE_URL, params=params, timeout=10)
        if response.status_code == 200:
            print("API key is valid. Connection to IEEE Xplore succeeded.")
        elif response.status_code == 403:
            print("Error 403: API key is invalid or lacks permissions.")
        else:
            print(f"Unexpected response: status {response.status_code}")
            print(response.text)
    except Exception as exc:
        print(f"Error during validation: {exc}")


def fetch_page(
    start_record: int,
    *,
    api_key: str,
    querytext: str,
    max_records: int,
) -> dict | None:
    """Fetch one page of results. Returns None on HTTP 429 (rate limit)."""
    params = {
        "apikey": api_key,
        "querytext": querytext,
        "max_records": max_records,
        "start_record": start_record,
        # sort_field and sort_order keep pagination stable across calls
        "sort_field": "article_number",
        "sort_order": "asc",
    }
    r = requests.get(BASE_URL, params=params, timeout=30)

    if r.status_code == 429:  # Too Many Requests
        time.sleep(2)
        return None
    r.raise_for_status()
    return r.json()


def normalize_authors(authors_obj: dict | None) -> str:
    if not authors_obj:
        return ""
    authors_list = authors_obj.get("authors", [])
    names = [a.get("full_name", "") for a in authors_list if a.get("full_name")]
    return "; ".join(names)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query IEEE Xplore API and export results to CSV."
    )
    parser.add_argument(
        "--api-key-file",
        default=os.environ.get("IEEE_API_KEY_FILE"),
        help=(
            "Path to a plain-text file containing the IEEE Xplore API key. "
            "Alternatively set the IEEE_API_KEY_FILE environment variable."
        ),
    )
    parser.add_argument(
        "--query",
        default="haptics AND wearable",
        help="Boolean search string for IEEE Xplore (default: 'haptics AND wearable').",
    )
    parser.add_argument(
        "--output",
        default="ieee_xplore_results.csv",
        help="Output CSV filename (default: ieee_xplore_results.csv).",
    )
    parser.add_argument(
        "--sleep",
        type=float,
        default=0.2,
        help="Seconds to sleep between paginated requests (default: 0.2).",
    )
    parser.add_argument(
        "--max-records",
        type=int,
        default=200,
        help="Records per API call, 1-200 (API hard ceiling is 200, default: 200).",
    )
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate the API key with a test request (uses 1 daily call), then exit.",
    )
    args = parser.parse_args()

    if not args.api_key_file:
        parser.error(
            "An API key file is required. Use --api-key-file or set IEEE_API_KEY_FILE."
        )

    api_key = read_api_key(args.api_key_file)

    if args.validate:
        validate_api_key(api_key)
        return

    start_record = 1
    all_rows: list[dict] = []

    first = fetch_page(
        start_record,
        api_key=api_key,
        querytext=args.query,
        max_records=args.max_records,
    )
    if not first:
        print("Could not fetch the first page (rate limit or error).")
        return

    totalfound = int(first.get("totalfound", 0))
    print(f"Total found: {totalfound}")

    articles = first.get("articles", [])
    while True:
        for a in articles:
            row = {
                "article_number": a.get("article_number", ""),
                "title": a.get("title", ""),
                "authors": normalize_authors(a.get("authors")),
                "publication_title": a.get("publication_title", ""),
                "publication_year": a.get("publication_year", ""),
                "doi": a.get("doi", ""),
                "abstract": a.get("abstract", ""),
                "pdf_url": a.get("pdf_url", ""),
                "html_url": a.get("html_url", ""),
            }
            all_rows.append(row)

        start_record += args.max_records
        if totalfound and start_record > totalfound:
            break

        time.sleep(args.sleep)
        data = fetch_page(
            start_record,
            api_key=api_key,
            querytext=args.query,
            max_records=args.max_records,
        )
        if not data:
            # Retry once after a longer wait if rate-limited
            time.sleep(2)
            data = fetch_page(
                start_record,
                api_key=api_key,
                querytext=args.query,
                max_records=args.max_records,
            )
            if not data:
                print("Stopped due to persistent rate limiting.")
                break

        articles = data.get("articles", [])
        if not articles:
            break

    fieldnames = [
        "article_number", "title", "authors", "publication_title",
        "publication_year", "doi", "abstract", "pdf_url", "html_url",
    ]
    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Done: {len(all_rows)} records saved to {args.output}")


if __name__ == "__main__":
    main()
