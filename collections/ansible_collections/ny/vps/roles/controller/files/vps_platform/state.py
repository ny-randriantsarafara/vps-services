import contextlib
import fcntl
import itertools
import json
import os
import tempfile
import time
from pathlib import Path

from .policy import Refused


def private_directory(path):
    path = Path(path)
    # Every managed ancestor below an existing trusted root must be private.
    missing = list(
        itertools.takewhile(lambda ancestor: not ancestor.exists(), [path, *path.parents])
    )
    for directory in reversed(missing):
        # Concurrent first requests create the state directory before the lock exists.
        directory.mkdir(mode=0o700, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise Refused("unsafe managed directory")
    os.chmod(path, 0o700)


def atomic_json(path, data):
    path = Path(path)
    private_directory(path.parent)
    replace_json(path, data, 0o600)


def replace_json(path, data, mode):
    """Atomically replace a JSON file inside an existing directory."""
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=".replace-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), mode)
            json.dump(data, stream, separators=(",", ":"), allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def append_json_line(path, data):
    path = Path(path)
    private_directory(path.parent)
    line = json.dumps(data, separators=(",", ":"), allow_nan=False) + "\n"
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        os.write(fd, line.encode())
        os.fsync(fd)
    finally:
        os.close(fd)


class Registry:
    def __init__(self, directory, lock_timeout_seconds):
        self.directory = Path(directory)
        self.path = self.directory / "registry.json"
        self.lock_timeout_seconds = lock_timeout_seconds

    @contextlib.contextmanager
    def locked(self):
        private_directory(self.directory)
        fd = os.open(
            self.directory / "controller.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
        try:
            self._acquire(fd)
            yield
        finally:
            os.close(fd)

    def _acquire(self, fd):
        deadline = time.monotonic() + self.lock_timeout_seconds
        while True:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise Refused(
                        "another operation holds the controller lock; retry later"
                    ) from None
                time.sleep(0.1)

    def load(self):
        if not self.path.exists():
            return {"protocol": 1, "instances": {}, "tombstones": {}}
        try:
            if self.path.is_symlink():
                raise ValueError
            state = json.loads(self.path.read_text())
            if (
                state["protocol"] != 1
                or not isinstance(state["instances"], dict)
                or not isinstance(state["tombstones"], dict)
            ):
                raise ValueError
            return state
        except (ValueError, KeyError, OSError):
            raise Refused("registry unreadable; operator reconciliation required") from None

    def save(self, state):
        atomic_json(self.path, state)
