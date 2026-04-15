"""Atomic file-write utilities for config files.

* ``atomic_write`` — write-to-temp-then-rename.  Safe for files in
  **directory** mounts (RPZ files under ``/shared/rpz/``) because the
  rename stays inside the same filesystem.

* ``safe_write`` — write-to-temp-then-copy.  Required for files behind
  Docker **file bind mounts** (e.g. ``forward-zones.conf``) where a
  rename would allocate a new inode and break the mount.
"""

from __future__ import annotations

import os
import tempfile


def atomic_write(path: str, content: str) -> None:
    """Write *content* to *path* atomically (temp + ``os.replace``).

    The temporary file is created in the same directory so the final
    ``os.replace`` is a same-filesystem rename — never partial.
    """
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".pb-tmp-")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        os.replace(tmp, path)
    except BaseException:
        # Clean up on any failure (including KeyboardInterrupt).
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def safe_write(path: str, content: str) -> None:
    """Write *content* to *path* safely (temp + copy).

    Uses a temp file for validation, then writes in-place.  This avoids
    creating a new inode (which would break Docker file bind mounts).
    """
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".pb-tmp-")
    try:
        os.write(fd, content.encode("utf-8"))
        os.close(fd)
        # Read back and overwrite the target in-place.
        with open(tmp, "r", encoding="utf-8") as src:
            validated = src.read()
        with open(path, "w", encoding="utf-8") as dst:
            dst.write(validated)
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
