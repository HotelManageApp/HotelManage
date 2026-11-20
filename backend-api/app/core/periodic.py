"""Small in-process scheduler for periodic jobs (overdue reminders, ...).

Each run gets its own session; a failing run is logged and the job keeps its schedule.
"""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.logging import get_logger

logger = get_logger(__name__)

Job = Callable[[AsyncSession], Awaitable[object]]


@dataclass(frozen=True)
class PeriodicJob:
    name: str
    every_seconds: float
    run: Job


class Scheduler:
    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker
        self._jobs: list[PeriodicJob] = []
        self._tasks: list[asyncio.Task[None]] = []

    def add(self, job: PeriodicJob) -> None:
        self._jobs.append(job)

    async def run_once(self, name: str) -> object:
        job = next(j for j in self._jobs if j.name == name)
        async with self._sessionmaker() as db:
            return await job.run(db)

    async def _loop(self, job: PeriodicJob) -> None:
        while True:
            try:
                async with self._sessionmaker() as db:
                    await job.run(db)
            except Exception:
                logger.exception("periodic_job_failed", job=job.name)
            await asyncio.sleep(job.every_seconds)

    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._loop(job), name=f"job:{job.name}") for job in self._jobs
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._tasks = []
