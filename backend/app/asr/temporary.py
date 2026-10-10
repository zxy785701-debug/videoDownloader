import os
import shutil
import time
import uuid
import logging
from contextlib import contextmanager

from ..analysis_errors import AnalysisError


def remove_workspace(root, path):
    if (path.resolve().parent != root.resolve() or path.is_symlink()
            or (hasattr(path, "is_junction") and path.is_junction())):
        raise ValueError("Refusing cleanup outside ASR temporary root")
    shutil.rmtree(path)


@contextmanager
def file_slot(path):
    """OS lock is released on crash, unlike a persisted 'busy' flag."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt
            if path.stat().st_size == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                yield False
                return
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                yield False
                return
        try:
            yield True
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def sweep(root):
    root.mkdir(parents=True, exist_ok=True)
    for path in root.iterdir():
        if (path.is_dir() and not path.is_symlink() and len(path.name) == 32
                and all(c in "0123456789abcdef" for c in path.name)
                and path.stat().st_mtime < time.time() - 86400):
            # All configured job deadlines are < 24h. Never traverse links.
            try:
                remove_workspace(root, path)
            except OSError:
                logging.getLogger(__name__).warning("ASR stale workspace cleanup deferred")


@contextmanager
def workspace(root, required_bytes=600 * 1024 * 1024):
    sweep(root)
    required_bytes = max(required_bytes, 600 * 1024 * 1024)
    if shutil.disk_usage(root).free < required_bytes:
        raise AnalysisError("ASR_DISK_LOW", f"临时目录可用空间不足 {required_bytes // (1024 * 1024)} MiB，已停止音频处理。")
    path = root / uuid.uuid4().hex
    path.mkdir(mode=0o700)
    try:
        yield path
    finally:
        try:
            remove_workspace(root, path)
        except OSError:
            logging.getLogger(__name__).warning("ASR workspace cleanup deferred")
