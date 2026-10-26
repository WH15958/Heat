"""Await synchronous device work without releasing request locks on cancellation."""
import asyncio


async def call_device(function, *args, **kwargs):
    worker = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        # Cancellation cannot stop a serial worker. Keep the caller's ownership
        # until it finishes, including when the request is cancelled repeatedly.
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if not worker.cancelled():
            worker.exception()
        raise
