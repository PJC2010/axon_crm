"""
Shared HTTP helper with retry + exponential backoff.

All outbound API calls (RentCast, Google, Census, contact provider)
should go through get_json so transient 5xx / 429 / timeout failures are retried
instead of silently dropping a property's enrichment.
"""
import logging
import time

import requests

from config import HTTP_BACKOFF, HTTP_RETRIES

log = logging.getLogger(__name__)

# Status codes worth retrying — transient server/rate-limit errors.
_RETRY_STATUS = {429, 500, 502, 503, 504}


def get_json(url, *, headers=None, params=None, timeout=30,
             retries=None, backoff=None):
    """GET `url` and return parsed JSON, retrying transient failures.

    Returns the decoded JSON on success, or None if every attempt failed.
    Raises nothing — callers already treat None as "no data".
    """
    retries = HTTP_RETRIES if retries is None else retries
    backoff = HTTP_BACKOFF if backoff is None else backoff

    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = requests.get(url, headers=headers, params=params, timeout=timeout)
            if resp.status_code in _RETRY_STATUS:
                last_err = f"HTTP {resp.status_code}"
                raise requests.HTTPError(last_err, response=resp)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            last_err = e
            # Don't sleep after the final attempt.
            if attempt < retries:
                delay = backoff * (2 ** attempt)
                log.debug("GET %s failed (%s); retry %d/%d in %.1fs",
                          url, e, attempt + 1, retries, delay)
                time.sleep(delay)

    log.warning("GET %s failed after %d attempts: %s", url, retries + 1, last_err)
    return None


def post_file_text(url, *, files=None, data=None, timeout=300,
                   retries=None, backoff=None):
    """POST a multipart file upload and return the response body as **text**.

    Same retry/backoff contract as get_json (returns None on failure, raises
    nothing). Needed for the Census batch geocoder, which takes a CSV file
    upload and answers with CSV rather than JSON. The default timeout is much
    longer than the JSON helpers' because a 10,000-address batch legitimately
    takes minutes to come back.
    """
    retries = HTTP_RETRIES if retries is None else retries
    backoff = HTTP_BACKOFF if backoff is None else backoff

    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, files=files, data=data, timeout=timeout)
            if resp.status_code in _RETRY_STATUS:
                last_err = f"HTTP {resp.status_code}"
                raise requests.HTTPError(last_err, response=resp)
            resp.raise_for_status()
            return resp.text
        except requests.RequestException as e:
            last_err = e
            if attempt < retries:
                delay = backoff * (2 ** attempt)
                log.debug("POST %s failed (%s); retry %d/%d in %.1fs",
                          url, e, attempt + 1, retries, delay)
                time.sleep(delay)

    log.warning("POST %s failed after %d attempts: %s", url, retries + 1, last_err)
    return None


def post_json(url, *, json=None, headers=None, timeout=30,
              retries=None, backoff=None):
    """POST `json` to `url` and return parsed JSON, retrying transient failures.

    Same retry/backoff contract as get_json (returns None on failure, raises
    nothing). Needed for providers whose API takes a JSON request body —
    e.g. BatchData's skip-trace endpoint.
    """
    retries = HTTP_RETRIES if retries is None else retries
    backoff = HTTP_BACKOFF if backoff is None else backoff

    last_err = None
    for attempt in range(retries + 1):
        try:
            resp = requests.post(url, json=json, headers=headers, timeout=timeout)
            if resp.status_code in _RETRY_STATUS:
                last_err = f"HTTP {resp.status_code}"
                raise requests.HTTPError(last_err, response=resp)
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, ValueError) as e:
            last_err = e
            if attempt < retries:
                delay = backoff * (2 ** attempt)
                log.debug("POST %s failed (%s); retry %d/%d in %.1fs",
                          url, e, attempt + 1, retries, delay)
                time.sleep(delay)

    log.warning("POST %s failed after %d attempts: %s", url, retries + 1, last_err)
    return None
