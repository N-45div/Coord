"""The live state and the one lock that serialises every read and write of it.

Holding a single lock for the whole of each request makes concurrent requests behave as
some serial order (§1, §11): no two writes interleave, no read sees half a write, and an
idempotency check and the write it guards are one step. Password hashing, the only slow
work, is done outside the lock.
"""
from __future__ import annotations

import threading

from .model import State


class Store:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.state = State()
