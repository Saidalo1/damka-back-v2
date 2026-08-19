"""A concurrent variant of channels' ``database_sync_to_async``.

channels' default is ``thread_sensitive=True``: every ORM call in a worker
process is funneled through a *single* shared thread, so a process can only run
one database operation at a time. Under WebSocket load (each move = SELECT +
UPDATE) that single thread becomes the bottleneck — throughput flatlines and
CPU cores sit idle while everything queues behind it.

This variant dispatches to the process-wide thread pool instead, so one worker
runs many DB ops concurrently. Each pool thread gets its own Django connection
(reused when CONN_MAX_AGE > 0), and channels' DatabaseSyncToAsync still calls
close_old_connections around every call. It is a drop-in replacement usable
both as a decorator (``@database_sync_to_async``) and inline
(``database_sync_to_async(obj.save)(...)``).

Correctness note: calls are still awaited sequentially within a single
consumer, so per-connection ordering is preserved; the added concurrency is
strictly *across* connections. Each decorated helper is self-contained
(its own autocommit op), so it does not share an in-flight transaction across
awaits — which is what would make non-thread-sensitive execution unsafe.
"""
from channels.db import DatabaseSyncToAsync


def database_sync_to_async(func):
    """Like channels.db.database_sync_to_async but thread_sensitive=False."""
    return DatabaseSyncToAsync(func, thread_sensitive=False)
