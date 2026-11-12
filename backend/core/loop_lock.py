"""Event-Loop-sichere asyncio-Sperre für Modul-Globals.

Der lokale Worker startet jeden Job mit `asyncio.run()` in einem eigenen Thread,
also mit einem NEUEN Event-Loop. Ein modulweites `asyncio.Lock()` bindet sich
beim ersten Warten an den damaligen Loop und wirft danach in jedem anderen Loop
„… is bound to a different event loop“. `LoopLock` hält je laufendem Loop eine
eigene Sperre und ist sonst ein 1:1-Ersatz (`async with`).
"""
import asyncio
import threading
import weakref


class LoopLock:
    def __init__(self):
        self._locks = weakref.WeakKeyDictionary()
        self._guard = threading.Lock()

    def _current(self) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        with self._guard:
            lock = self._locks.get(loop)
            if lock is None:
                lock = self._locks[loop] = asyncio.Lock()
            return lock

    def locked(self) -> bool:
        return self._current().locked()

    async def acquire(self) -> bool:
        return await self._current().acquire()

    def release(self) -> None:
        self._current().release()

    async def __aenter__(self):
        await self.acquire()
        return None

    async def __aexit__(self, exc_type, exc, tb):
        self.release()
