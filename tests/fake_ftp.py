"""
fake_ftp.py
====================
In-memory stand-in for ftplib.FTP, covering exactly the methods
pipeline/fetch.py and utils/ftp_utils.py call (cwd, pwd, login, quit,
retrbinary, size, mlsd). No real socket/network involved.

FakeFTPWorld is the shared backing store; FakeFTP is a connection into it.
Multiple FakeFTP instances can point at the same world, so pool-based tests
(Phase 5) can assert per-worker connection counts while sharing one fake
remote filesystem.
"""

import collections
from ftplib import error_perm, error_temp


class FakeFile:
    """One remote file. size_sequence, if set, overrides size() to return a
    different value on each successive call (simulating a file mid-write,
    for Phase 4's poll-size-hai-lần); once exhausted, the last value repeats.
    retr_fail_count: the first N retrbinary() calls raise error_temp (simulating
    a transient server hiccup), then subsequent calls transfer normally.
    size_fail: every size() call raises error_perm (simulating a server that
    doesn't support/answer SIZE), independent of the file otherwise being
    downloadable via retrbinary — for Phase 2's "SIZE inconclusive" branch."""

    def __init__(self, content: bytes, mtime: str = "20260810000000",
                 size_sequence=None, retr_fail_count: int = 0, size_fail: bool = False):
        self.content = content
        self.mtime = mtime
        self.size_sequence = size_sequence
        self._size_calls = 0
        self.retr_fail_count = retr_fail_count
        self.retr_calls = 0
        self.size_fail = size_fail


class FakeFTPWorld:
    """Fake remote filesystem + connection bookkeeping for one test."""

    def __init__(self):
        self.dirs = collections.defaultdict(dict)   # path -> {filename: FakeFile}
        self.unreachable = set()                     # paths whose cwd() raises error_perm
        self.login_failures = []                     # exceptions to raise on next login() calls, in order
        self.connections = []                         # every FakeFTP created against this world

    def add_file(self, path: str, filename: str, content: bytes, **kwargs):
        self.dirs[path][filename] = FakeFile(content, **kwargs)

    def mark_unreachable(self, path: str):
        self.unreachable.add(path)


class FakeFTP:
    def __init__(self, *args, world: FakeFTPWorld, **kwargs):
        self.world = world
        self.cwd_path = "/"
        self.closed = False
        self.login_calls = []
        self.cwd_calls = []   # every path passed to cwd(), success or failure, for asserting call counts
        world.connections.append(self)

    # ----- connection lifecycle -----
    def login(self, user, password):
        self.login_calls.append((user, password))
        if self.world.login_failures:
            exc = self.world.login_failures.pop(0)
            if exc is not None:
                raise exc

    def quit(self):
        self.closed = True

    # ----- navigation -----
    def pwd(self):
        return self.cwd_path

    def cwd(self, path):
        self.cwd_calls.append(path)
        if path in self.world.unreachable:
            raise error_perm(f"550 {path}: No such directory")
        self.cwd_path = path

    # ----- file transfer -----
    def retrbinary(self, cmd, callback):
        _, filename = cmd.split(" ", 1)
        f = self.world.dirs.get(self.cwd_path, {}).get(filename)
        if f is None:
            raise error_perm(f"550 {filename}: No such file")
        f.retr_calls += 1
        if f.retr_calls <= f.retr_fail_count:
            raise error_temp(f"426 {filename}: Connection closed; transfer aborted")
        callback(f.content)

    def size(self, filename):
        f = self.world.dirs.get(self.cwd_path, {}).get(filename)
        if f is None:
            raise error_perm(f"550 {filename}: No such file")
        if f.size_fail:
            raise error_perm("500 SIZE not understood")
        if f.size_sequence is not None:
            idx = min(f._size_calls, len(f.size_sequence) - 1)
            f._size_calls += 1
            return f.size_sequence[idx]
        f._size_calls += 1
        return len(f.content)

    def mlsd(self, path=""):
        target = path or self.cwd_path
        for name, f in self.world.dirs.get(target, {}).items():
            yield name, {"type": "file", "size": str(len(f.content)), "modify": f.mtime}


def make_ftp_factory(world: FakeFTPWorld):
    """Drop-in replacement for ftplib.FTP's constructor: ignores host/timeout
    args, always returns a new FakeFTP bound to `world`."""
    def _factory(*args, **kwargs):
        return FakeFTP(*args, world=world, **kwargs)
    return _factory
