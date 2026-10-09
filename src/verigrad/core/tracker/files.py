"""Removing snapshot folders on permanent delete. Only ever inside `<data_dir>/snapshots/`."""

import logging
import shutil
from pathlib import Path

log = logging.getLogger(__name__)


def remove_snapshot_folders(data_dir: Path, dirs: list[str]) -> tuple[list[str], list[str]]:
    """Remove each folder (relative to the data dir), then prune emptied parents up to
    `snapshots/`. Returns (removed, errors). A path outside `snapshots/` is never touched."""
    root = (data_dir / "snapshots").resolve()
    removed: list[str] = []
    errors: list[str] = []
    for relative in dirs:
        target = (data_dir / relative).resolve()
        if target == root or not target.is_relative_to(root):
            errors.append(f"{relative}: outside the snapshots folder, not removed")
            continue
        try:
            if target.exists():
                shutil.rmtree(target)
            removed.append(relative)
        except OSError as exc:
            log.warning("could not remove snapshot folder %s: %s", target, exc)
            errors.append(f"{relative}: {exc}")
            continue
        _prune_empty_parents(target.parent, root)
    return removed, errors


def _prune_empty_parents(folder: Path, root: Path) -> None:
    while folder != root and folder.is_relative_to(root):
        try:
            folder.rmdir()  # only succeeds when empty
        except OSError:
            return
        folder = folder.parent
