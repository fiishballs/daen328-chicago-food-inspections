import logging
import time

import pandas as pd
import requests
from sodapy import Socrata

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

DOMAIN = "data.cityofchicago.org"
DATASET_ID = "4ijn-s7e5"

MAX_RETRIES = 5
BACKOFF_SECONDS = 2  # doubles on each retry: 2, 4, 8, 16, ...
RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class ExtractionError(Exception):
    """Raised when data extraction fails after all retries."""


def fetch_page(client, limit, offset):
    """Fetch one page of results, retrying on transient errors."""
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Ordering by :id keeps pagination stable between requests
            return client.get(DATASET_ID, limit=limit, offset=offset, order=":id")

        except requests.exceptions.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status not in RETRYABLE_STATUS_CODES:
                # 400/401/403/404 etc. won't fix themselves, so fail immediately
                raise ExtractionError(f"Non-retryable HTTP error {status}: {e}") from e
            logger.warning("HTTP %s at offset %d (attempt %d/%d)", status, offset, attempt, MAX_RETRIES)

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            logger.warning("Network error at offset %d (attempt %d/%d): %s", offset, attempt, MAX_RETRIES, e)

        if attempt < MAX_RETRIES:
            wait = BACKOFF_SECONDS * 2 ** (attempt - 1)
            logger.info("Retrying in %ds...", wait)
            time.sleep(wait)

    raise ExtractionError(f"Failed to fetch offset {offset} after {MAX_RETRIES} attempts")


def extract_data(limit, return_partial=False):
    """
    Download every record from the dataset, `limit` rows at a time.

    If return_partial is True, a failure part-way through returns whatever
    was downloaded so far instead of raising.
    """
    if not isinstance(limit, int) or limit <= 0:
        raise ValueError(f"limit must be a positive integer, got {limit!r}")

    all_data = []
    client = Socrata(DOMAIN, None, timeout=30)

    try:
        while True:
            try:
                results = fetch_page(client, limit, offset=len(all_data))
            except ExtractionError as e:
                if return_partial and all_data:
                    logger.error("%s. Returning %d partial records.", e, len(all_data))
                    break
                raise

            if not results:
                break

            all_data.extend(results)
            logger.info("Total records so far: %d", len(all_data))

    except KeyboardInterrupt:
        logger.warning("Interrupted by user after %d records.", len(all_data))
        if not return_partial:
            raise
    finally:
        client.close()  # always release the HTTP session

    logger.info("Final result count: %d", len(all_data))

    if not all_data:
        logger.warning("No records returned; producing an empty DataFrame.")
        return pd.DataFrame()

    try:
        return pd.DataFrame.from_records(all_data)
    except (ValueError, TypeError) as e:
        raise ExtractionError(f"Could not build DataFrame from results: {e}") from e


if __name__ == "__main__":
    try:
        df = extract_data(2000)
        print(df.head())
    except (ExtractionError, ValueError) as e:
        logger.error("Extraction failed: %s", e)
        raise SystemExit(1)