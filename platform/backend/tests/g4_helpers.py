"""G4 통합 시험은 기존 실제 로컬 HVC→worker→영속 G3 결과 fixture를 소비한다."""
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

from services import training_round_service


def completed_live_result(tmp_path):
    path = Path(__file__).with_name("test_live_training.py")
    spec = spec_from_file_location("g4_live_fixture", path)
    fixture = module_from_spec(spec)
    spec.loader.exec_module(fixture)
    entry, _envelopes, _data = fixture.leaves_for_flat(tmp_path)
    return training_round_service.aggregate_round(entry["round_id"])
