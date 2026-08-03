from __future__ import annotations

from unittest.mock import MagicMock

from app.dashboard import scheduler


def test_daily_reset_tolerates_scheduler_jitter(monkeypatch) -> None:
    fake = MagicMock()
    monkeypatch.setattr(scheduler, "_scheduler", None)
    monkeypatch.setattr(scheduler, "BackgroundScheduler", lambda **_kwargs: fake)

    scheduler.start_scheduler()

    assert fake.add_job.call_count == 1
    kwargs = fake.add_job.call_args.kwargs
    assert kwargs["misfire_grace_time"] == 300
    assert kwargs["coalesce"] is True
    assert kwargs["max_instances"] == 1
    fake.start.assert_called_once_with()

    scheduler._scheduler = None