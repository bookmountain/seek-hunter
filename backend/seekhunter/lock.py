import fcntl
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


class RunLocked(Exception):
    pass


@contextmanager
def run_lock(data_dir: Path, blocking: bool = False) -> Iterator[None]:
    data_dir.mkdir(parents=True, exist_ok=True)
    with open(data_dir / "run.lock", "w") as fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_EX if blocking else fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as e:
            raise RunLocked("another run is in progress") from e
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)
