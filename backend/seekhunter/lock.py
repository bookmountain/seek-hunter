import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class RunLocked(Exception):
    pass


@contextmanager
def run_lock(data_dir: Path, blocking: bool = False, name: str = "run.lock") -> Iterator[None]:
    """Exclusive flock on `<data_dir>/<name>`. Crawls use `run.lock`; tailoring uses `tailor.lock`."""
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / name, "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise RunLocked(f"another process holds {name}") from e
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
