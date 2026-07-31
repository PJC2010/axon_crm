"""
Per-step elapsed timing for a pipeline run.

Pure and dependency-free (no DB, no network, no imports from pipeline.db) so it
can be unit-tested with a fake clock — same split as pipeline/equity.py and
pipeline/job_value.py.

Why this exists: seeding a ZIP is a sequence of ~11 steps with wildly different
cost profiles (serial paid HTTP loops vs. full-table Python round trips vs. cheap
aggregates). Wall-clock for the whole run cannot distinguish them, so each step is
timed individually and reported with the row count it processed. The derived
`sec_per_1k` is the metric that actually separates per-row overhead from a fixed
per-step cost: a step that is slow because it downloads one big payload has a
`sec_per_1k` that falls as the ZIP grows, while a step that is slow because it
loops in Python holds roughly steady.

Usage:

    timer = StepTimer(probe=some_probe)
    with timer.step("seed") as s:
        s.rows = seed(...)
    log.info("%s", timer.format_table())
    result["timings"] = timer.as_dict()
"""
import time
from contextlib import contextmanager


class Step:
    """Mutable handle yielded by StepTimer.step().

    Callers set `rows` to the number of records the step processed. `note` is
    free-form and carries whatever the timer's probe returned (upsert stats, in
    practice). Both stay None when the step doesn't report them.
    """

    __slots__ = ("name", "rows", "note")

    def __init__(self, name: str):
        self.name = name
        self.rows = None
        self.note = None


class StepTimer:
    """Records elapsed seconds per named step, in call order.

    `clock` is injectable so tests are deterministic without sleeping.

    `probe` is an optional object with `reset()` and `read()`. It is reset when a
    step begins and read when it ends, and whatever `read()` returns is attached
    to that step. This is how DB-level counters attach without this module ever
    importing the DB layer.
    """

    def __init__(self, clock=time.perf_counter, probe=None):
        self._clock = clock
        self._probe = probe
        self._steps: list[dict] = []
        self._t0 = clock()

    @contextmanager
    def step(self, name: str):
        handle = Step(name)
        if self._probe is not None:
            self._probe.reset()
        start = self._clock()
        try:
            yield handle
        finally:
            # Recorded in `finally` so a step that raises still reports its
            # duration. A run that dies partway is exactly when the numbers
            # matter most, so the timing must survive the exception.
            elapsed = self._clock() - start
            if handle.note is None and self._probe is not None:
                handle.note = self._probe.read()
            self._steps.append(self._entry(handle, elapsed))

    @staticmethod
    def _entry(handle: Step, elapsed: float) -> dict:
        entry = {
            "step": handle.name,
            "seconds": round(elapsed, 2),
            "rows": handle.rows,
        }
        entry["sec_per_1k"] = _sec_per_1k(elapsed, handle.rows)
        if handle.note:
            entry["upsert"] = handle.note
        return entry

    def total_seconds(self) -> float:
        """Wall-clock since the timer was created.

        Deliberately not the sum of the steps: the gap between the two is itself
        a signal (GC pauses, swap, contention with request serving).
        """
        return round(self._clock() - self._t0, 2)

    def steps(self) -> list[dict]:
        return list(self._steps)

    def slowest(self, n: int = 3) -> list[str]:
        ranked = sorted(self._steps, key=lambda e: e["seconds"], reverse=True)
        return [e["step"] for e in ranked[:n]]

    def as_dict(self) -> dict:
        steps = self.steps()
        return {
            "steps": steps,
            "total_seconds": self.total_seconds(),
            "step_seconds": round(sum(e["seconds"] for e in steps), 2),
            "slowest": self.slowest(),
        }

    def format_table(self, title: str = "") -> str:
        """Aligned text block for a single log line.

        Emitted at the end of each ZIP so the live log carries the result even
        when the run is later cancelled and `result_json` is never written.
        """
        steps = self.steps()
        head = f"Step timings{f' — {title}' if title else ''}:"
        if not steps:
            return f"{head} (no steps recorded)"

        lines = [head, f"    {'step':22}  {'secs':>8}  {'rows':>9}  {'s/1k':>7}  upsert"]
        for e in steps:
            rows = "—" if e["rows"] is None else f"{e['rows']:,}"
            per_k = "—" if e["sec_per_1k"] is None else f"{e['sec_per_1k']:.2f}"
            lines.append(
                f"    {e['step']:22}  {e['seconds']:>8.2f}  {rows:>9}  {per_k:>7}  "
                f"{_fmt_upsert(e.get('upsert'))}"
            )
        total = self.total_seconds()
        step_sum = sum(e["seconds"] for e in steps)
        lines.append(f"    {'TOTAL':22}  {total:>8.2f}")
        # A large unaccounted gap points at the environment (GC, swap, CPU
        # contention) rather than at any individual step.
        if total - step_sum > 1.0:
            lines.append(f"    {'(unaccounted)':22}  {total - step_sum:>8.2f}")
        lines.append(f"    slowest: {', '.join(self.slowest())}")
        return "\n".join(lines)


def _sec_per_1k(elapsed: float, rows) -> float | None:
    """Seconds per 1,000 rows, or None when there is no meaningful row count."""
    if not rows or rows <= 0:
        return None
    return round(elapsed * 1000.0 / rows, 3)


def _fmt_upsert(stats: dict | None) -> str:
    """Render upsert counters compactly: writes/groups/rows and their seconds.

    `groups` is the number of distinct column signatures upsert_properties split
    the batch into — a high count means the batching fragmented.
    """
    if not stats:
        return ""
    return (f"{stats.get('calls', 0)} calls/{stats.get('groups', 0)} groups/"
            f"{stats.get('rows', 0):,} rows in {stats.get('seconds', 0.0):.2f}s")
