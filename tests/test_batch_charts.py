import json
from unittest.mock import patch

from src.experiment.batch_charts import chart_run, saved_charts


def test_actual_times_and_missing_readings():
    result = chart_run(dict(run_id="r", started_at="2026-11-09T18:00:00", total_duration=100,
        steps=[dict(step_id="hold", started_at="2026-11-09T18:00:10", finished_at="2026-11-09T18:01:10")],
        sensor_data=dict(microwaves=dict(microwave1=dict(material_temperature=[
            dict(t=0, v=70), dict(t=5, v=None), dict(t=40, v=80)])))), 1)
    assert result["phases"] == [0, 0, 60, 0, 0, 0, 40]
    assert result["target"] is None
    assert result["temperature"][0]["points"] == [[0, 70], [5/60, None], [5.01/60, None], [40/60, 80]]


def test_terminal_cache_survives_new_reads_without_loading_runs(tmp_path):
    record = dict(batch_id="guided_test", state="completed", groups=[dict(index=1, run_id="r", state="completed")])
    with patch("src.experiment.batch_charts.get_experiment_run", return_value=dict(run_id="r")) as load:
        first = saved_charts(record, tmp_path)
        assert first["saved"]
        assert load.call_count == 1
    with patch("src.experiment.batch_charts.get_experiment_run", side_effect=AssertionError("must use saved report")):
        assert saved_charts(record, tmp_path) == first
    assert json.loads((tmp_path / "charts/guided_test.json").read_text())["saved"]


def test_missing_log_not_cached_and_later_recovered(tmp_path):
    record = dict(batch_id="guided_test", state="completed", groups=[dict(index=1, run_id="r")])
    with patch("src.experiment.batch_charts.get_experiment_run", return_value=None):
        assert saved_charts(record, tmp_path)["missing"] == [1]
    assert not (tmp_path / "charts/guided_test.json").exists()
    with patch("src.experiment.batch_charts.get_experiment_run", return_value=dict(run_id="r")):
        assert saved_charts(record, tmp_path)["saved"]


def test_running_batch_not_cached_and_identity_change_rebuilds(tmp_path):
    record = dict(batch_id="guided_test", state="running", groups=[dict(index=1, run_id="r")])
    with patch("src.experiment.batch_charts.get_experiment_run", return_value=dict(run_id="r")):
        assert not saved_charts(record, tmp_path)["saved"]
        record["state"] = "completed"
        assert saved_charts(record, tmp_path)["saved"]
    record["groups"].append(dict(index=2, run_id="s"))
    with patch("src.experiment.batch_charts.get_experiment_run", side_effect=lambda rid: dict(run_id=rid)) as load:
        assert len(saved_charts(record, tmp_path)["models"]) == 2
        assert load.call_count == 2
