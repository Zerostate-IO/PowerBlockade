from __future__ import annotations

import logging
import os
import shutil
import tempfile
import urllib.request

from app.services.rpz import parse_blocklist_lines

log = logging.getLogger(__name__)


def fetch_and_parse_blocklist(url: str, fmt: str) -> set[str]:
    """
    Downloads blocklist to a temporary file, parses it, and returns the domains.
    Ensures the temporary file is deleted after processing.
    """
    fd, temp_path = tempfile.mkstemp(prefix="pb_blocklist_", suffix=".txt")
    # mkstemp returns an open file descriptor, which we must close or use.
    # We'll close it and let urllib/open handle it.
    os.close(fd)

    try:
        log.info(f"Downloading blocklist from {url} to {temp_path}")

        # Use a custom user agent to avoid being blocked by some lists
        req = urllib.request.Request(
            url,
            data=None,
            headers={"User-Agent": "PowerBlockade/0.1.0"},
        )

        with urllib.request.urlopen(req, timeout=60) as response:
            with open(temp_path, "wb") as out_file:
                shutil.copyfileobj(response, out_file)

        log.info(f"Parsing blocklist from {temp_path}")
        with open(temp_path, "r", encoding="utf-8", errors="ignore") as f:
            # Pass the file object directly; it is iterable over lines
            return parse_blocklist_lines(f, fmt)

    except Exception as e:
        log.error(f"Failed to fetch/parse blocklist {url}: {e}")
        raise
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
                log.debug(f"Deleted temporary file {temp_path}")
            except OSError as e:
                log.warning(f"Failed to delete temporary file {temp_path}: {e}")
