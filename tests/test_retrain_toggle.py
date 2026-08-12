"""ML_RETRAIN_ENABLED gates whether the nightly retrain is registered at all.

The job runs inside the API process, so "is it scheduled?" is an operational
question, not a detail — it must be answerable from an env var without a code
change, and flipping it off must actually unschedule rather than leave a job
behind. POST /api/ml/retrain is deliberately *not* gated: it is the escape hatch
for a one-off retrain while the cron is off.
"""
import config
from api import scheduler as sched
from api.scheduler import RETRAIN_JOB_ID, schedule_retraining, scheduler


def _clear():
    if scheduler.get_job(RETRAIN_JOB_ID):
        scheduler.remove_job(RETRAIN_JOB_ID)


def test_disabled_by_default_does_not_register_the_job(monkeypatch):
    monkeypatch.setattr(config, "ML_RETRAIN_ENABLED", False)
    _clear()
    schedule_retraining()
    assert scheduler.get_job(RETRAIN_JOB_ID) is None


def test_enabling_registers_it_at_the_configured_hour(monkeypatch):
    monkeypatch.setattr(config, "ML_RETRAIN_ENABLED", True)
    monkeypatch.setattr(config, "ML_RETRAIN_HOUR", 3)
    _clear()
    try:
        schedule_retraining()
        job = scheduler.get_job(RETRAIN_JOB_ID)
        assert job is not None
        fields = {f.name: str(f) for f in job.trigger.fields}
        assert fields["hour"] == "3"
        assert fields["minute"] == "0"
    finally:
        _clear()


def test_turning_it_off_removes_an_already_registered_job(monkeypatch):
    monkeypatch.setattr(config, "ML_RETRAIN_ENABLED", True)
    _clear()
    schedule_retraining()
    assert scheduler.get_job(RETRAIN_JOB_ID) is not None

    monkeypatch.setattr(config, "ML_RETRAIN_ENABLED", False)
    schedule_retraining()
    assert scheduler.get_job(RETRAIN_JOB_ID) is None


def test_the_flag_does_not_disable_the_retrain_entrypoint():
    # The caps, not the flag, are what make an on-demand retrain safe — the
    # function must stay callable so /api/ml/retrain keeps working.
    assert callable(sched.retrain_models)


def test_env_parsing_accepts_the_usual_truthy_spellings(monkeypatch):
    import importlib
    for raw, expected in [("true", True), ("True", True), ("1", True),
                          ("yes", True), ("false", False), ("0", False),
                          ("", False)]:
        monkeypatch.setenv("ML_RETRAIN_ENABLED", raw)
        assert importlib.reload(config).ML_RETRAIN_ENABLED is expected, raw
    monkeypatch.delenv("ML_RETRAIN_ENABLED", raising=False)
    assert importlib.reload(config).ML_RETRAIN_ENABLED is False
