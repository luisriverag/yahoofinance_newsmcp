import threading
from datetime import datetime, timedelta, timezone

import pytest

from yahoofinance_newsmcp.scheduler import MorningScheduler, next_run_after, parse_hhmm, resolve_timezone

TZ = timezone.utc


def test_parse_hhmm_valid():
    assert parse_hhmm("07:30").strftime("%H:%M") == "07:30"
    assert parse_hhmm(" 7:05 ").strftime("%H:%M") == "07:05"


@pytest.mark.parametrize("bad", ["7", "24:00", "12:60", "noon", "7:30am", ""])
def test_parse_hhmm_invalid(bad):
    with pytest.raises(ValueError):
        parse_hhmm(bad)


def test_resolve_timezone_known():
    assert resolve_timezone("America/New_York").key == "America/New_York"


def test_resolve_timezone_unknown_falls_back_to_utc():
    assert resolve_timezone("Mars/Olympus").key == "UTC"


def test_next_run_after_earlier_today():
    now = datetime(2026, 1, 1, 10, 0, tzinfo=TZ)
    nxt = next_run_after(now, parse_hhmm("07:00"))
    assert nxt == datetime(2026, 1, 2, 7, 0, tzinfo=TZ)


def test_next_run_after_later_today():
    now = datetime(2026, 1, 1, 6, 0, tzinfo=TZ)
    nxt = next_run_after(now, parse_hhmm("07:00"))
    assert nxt == datetime(2026, 1, 1, 7, 0, tzinfo=TZ)


def test_next_run_after_exactly_at_time_goes_to_next_day():
    now = datetime(2026, 1, 1, 7, 0, 0, tzinfo=TZ)
    nxt = next_run_after(now, parse_hhmm("07:00"))
    assert nxt == datetime(2026, 1, 2, 7, 0, tzinfo=TZ)


def test_next_run_always_strictly_future():
    now = datetime(2026, 1, 1, 12, 0, 0, tzinfo=TZ)
    for hhmm in ("00:00", "12:00", "23:59"):
        assert next_run_after(now, parse_hhmm(hhmm)) > now


def test_scheduler_start_runs_callback(monkeypatch):
    fired = threading.Event()
    scheduler = MorningScheduler("07:00", "UTC", fired.set)
    monkeypatch.setattr(
        scheduler,
        "next_run",
        lambda *a: datetime.now(TZ) + timedelta(seconds=0.2),
    )
    scheduler.start()
    try:
        assert fired.wait(timeout=5), "scheduler never fired"
    finally:
        scheduler.stop()


def test_scheduler_run_once_runs_now_and_survives_errors():
    calls = []

    def callback():
        calls.append(1)

    scheduler = MorningScheduler("07:00", "UTC", callback)
    scheduler.run_once()
    assert calls == [1]

    def boom():
        raise RuntimeError("expected")

    scheduler = MorningScheduler("07:00", "UTC", boom)
    scheduler.run_once()


def test_scheduler_next_run_handles_dst_transitions():
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo("America/New_York")
    except Exception:
        pytest.skip("zoneinfo not available")

    summer = datetime(2026, 7, 1, 12, 0, tzinfo=tz)
    nxt = next_run_after(summer, parse_hhmm("07:00"))
    assert nxt.tzinfo == tz
    assert nxt.hour == 7

    winter = datetime(2026, 12, 1, 12, 0, tzinfo=tz)
    nxt2 = next_run_after(winter, parse_hhmm("07:00"))
    assert nxt2.tzinfo == tz
    assert nxt2.hour == 7


@pytest.mark.parametrize(
    "tzname",
    ["America/New_York", "Europe/London", "Asia/Tokyo"],
)
def test_scheduler_next_run_different_timezones(tzname):
    try:
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(tzname)
    except Exception:
        pytest.skip("zoneinfo not available")

    now = datetime(2026, 1, 1, 18, 0, tzinfo=tz)
    nxt = next_run_after(now, parse_hhmm("07:00"))
    assert nxt.tzinfo == tz
    assert nxt.hour == 7
    assert nxt.date() == (now.date() + timedelta(days=1))
