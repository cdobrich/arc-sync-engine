from __future__ import annotations

from archive_sync_engine.rate_limit import OperationRateLimiter


def test_rate_limiter_delays_only_between_operations() -> None:
    now = 100.0
    sleeps: list[float] = []

    def monotonic() -> float:
        return now

    def sleep(seconds: float) -> None:
        sleeps.append(seconds)

    limiter = OperationRateLimiter(
        between_messages_seconds=0.5,
        between_channels_seconds=2.0,
        sleep=sleep,
        monotonic=monotonic,
    )

    limiter.before_message()
    limiter.before_message()
    limiter.before_channel()
    limiter.before_channel()

    assert sleeps == [0.5, 2.0]


def test_rate_limiter_zero_delays_do_not_sleep() -> None:
    sleeps: list[float] = []
    limiter = OperationRateLimiter(
        sleep=sleeps.append,
        monotonic=lambda: 100.0,
    )

    limiter.before_message()
    limiter.before_channel()
    limiter.before_message()
    limiter.before_channel()

    assert sleeps == []
