"""Never overwrite malformed sample history while appending or deleting runs."""
import csv
import io

import pytest

from src.science import sample_record as samples
from src.science.sample_id import generate_unique_sample_id
from src.experiment.experiment_logger import ExperimentLogger


@pytest.mark.parametrize('contents', [
    'broken-header\nold-data\n',
    'sample_id,run_id,run_id\nS1,R1,R2\n',
    'sample_id,run_id\nS1,R1,unexpected\n',
    'sample_id,run_id\nS1\n',
    'sample_id,run_id\n"S1,R1\n',
    '"sample_id,run_id\nS1,R1\n',
])
def test_malformed_samples_block_writes_deletion_and_id_generation(contents):
    samples.SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    samples.SAMPLES_CSV.write_text(contents, encoding='utf-8')
    original = samples.SAMPLES_CSV.read_bytes()
    with pytest.raises(OSError):
        generate_unique_sample_id({'sample_id': 'new'})
    assert not samples.write_sample_record('new-run', {'sample_id': 'new'})
    with pytest.raises(OSError):
        samples.remove_sample_records_for_run_ids(['R1'])
    assert samples.SAMPLES_CSV.read_bytes() == original


def test_appending_preserves_extra_columns_and_legacy_headers():
    samples.SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    samples.SAMPLES_CSV.write_text('sample_id,run_id,lab_note\nS1,R1,保留原始备注\n', encoding='utf-8')
    assert samples.write_sample_record('R2', {'sample_id': 'S2'})
    rows = list(csv.DictReader(io.StringIO(samples.SAMPLES_CSV.read_text(encoding='utf-8'))))
    assert rows[0]['lab_note'] == '保留原始备注'
    assert rows[1]['run_id'] == 'R2' and rows[1]['lab_note'] == ''
    assert samples.remove_sample_records_for_run_ids(['R2']) == 1
    assert '保留原始备注' in samples.SAMPLES_CSV.read_text(encoding='utf-8')


def test_nonstrict_inspection_keeps_ids_read_before_a_malformed_row():
    samples.SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    samples.SAMPLES_CSV.write_text('run_id,sample_id\nR1,S1\nR2\n', encoding='utf-8')
    assert samples.existing_sample_ids() == {'S1'}
    with pytest.raises(OSError):
        samples.existing_sample_ids(strict=True)


def test_corruption_during_run_is_reported_as_persistence_failure():
    log = ExperimentLogger(save_log=True)
    log.start_run('audit', 'audit.yaml', 0)
    samples.SAMPLES_DIR.mkdir(parents=True, exist_ok=True)
    samples.SAMPLES_CSV.write_text('broken-header\noriginal\n', encoding='utf-8')
    original = samples.SAMPLES_CSV.read_bytes()
    assert log.finish_run('completed') is False
    assert log.active_run.persistence_status == 'error'
    assert samples.SAMPLES_CSV.read_bytes() == original
