"""No test may reach a network: the library and both free commands promise to make no network call.

``tests/test_boundaries.py`` checks, by reading the source, that no module imports a networking
library. That cannot see a network call made through a module it allows (``urllib`` reached
through a dependency, a DNS lookup hidden in a helper). So every test also runs with Python's
socket interface blocked, the way pytest-socket does: opening an Internet socket, connecting,
or resolving a name raises :class:`NetworkBlocked`. Local Unix sockets stay allowed, because an
``asyncio`` event loop opens a pair of them to wake itself.

Processes a test starts (git, ``python -m bohrin``) are outside this guard; git is run with
``protocol.allow=never``, and the command-line tests also run in-process under the guard.
"""

from __future__ import annotations

import socket
from collections.abc import Iterator
from typing import Any

import pytest


class NetworkBlocked(RuntimeError):
    """A test tried to reach a network."""


_REAL_SOCKET = socket.socket


class _GuardedSocket(_REAL_SOCKET):
    def __init__(self, family: Any = socket.AF_INET, *args: Any, **kwargs: Any) -> None:
        if family != getattr(socket, "AF_UNIX", object()):
            raise NetworkBlocked(f"a test opened a network socket (family {family!r})")
        super().__init__(family, *args, **kwargs)


def _blocked(name: str) -> Any:
    def refuse(*_args: Any, **_kwargs: Any) -> Any:
        raise NetworkBlocked(f"a test called socket.{name}")

    return refuse


@pytest.fixture(autouse=True, scope="session")
def _no_network() -> Iterator[None]:
    patched = {
        "socket": _GuardedSocket,
        "create_connection": _blocked("create_connection"),
        "getaddrinfo": _blocked("getaddrinfo"),
        "gethostbyname": _blocked("gethostbyname"),
        "gethostbyname_ex": _blocked("gethostbyname_ex"),
        "gethostbyaddr": _blocked("gethostbyaddr"),
    }
    saved = {name: getattr(socket, name) for name in patched}
    for name, value in patched.items():
        setattr(socket, name, value)
    try:
        yield
    finally:
        for name, value in saved.items():
            setattr(socket, name, value)
