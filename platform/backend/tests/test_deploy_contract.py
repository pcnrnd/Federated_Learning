"""사일로 배포 계약 (F9) — 워커는 마운트로 들어가고(docker cp 없음) 수집기는 기동 때 자동 시작"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PLATFORM = Path(__file__).resolve().parents[2]
SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
SILOS = [f"silo-{i}" for i in range(1, 7)]
WORKER = "/opt/silo_scripts/silo_worker.py"


@pytest.fixture(scope="module")
def services() -> dict:
    return yaml.safe_load((PLATFORM / "compose.yaml").read_text(encoding="utf-8"))["services"]


@pytest.mark.unit
def test_silos_mount_worker_scripts_and_sdk_read_only(services):
    for silo in SILOS:
        volumes = services[silo]["volumes"]
        assert "./backend/scripts:/opt/silo_scripts:ro" in volumes, silo
        assert "./backend/silo_sdk:/opt/silo_sdk:ro" in volumes, silo


@pytest.mark.unit
def test_silo_environment_names_the_silo_and_central(services):
    for silo in SILOS:
        env = services[silo]["environment"]
        assert env["FED_SILO_ID"] == silo
        assert env["FED_CENTRAL"] == "http://fed-backend:8000"
        assert env["FED_SILO_DATA_DIR"] == "/srv/silo-data"
        assert env["FED_ALIGN_KEY"] == "${FED_ALIGN_KEY:-}"
        assert env["FED_MONITOR_AUTOSTART"] == "${FED_MONITOR_AUTOSTART:-1}"


@pytest.mark.unit
def test_align_key_is_never_given_to_the_backend(services):
    assert "FED_ALIGN_KEY" not in services["backend"].get("environment", {})


@pytest.mark.unit
@pytest.mark.parametrize("n", range(1, 7))
def test_entrypoint_autostarts_monitor_under_a_restart_loop(n):
    text = (PLATFORM / "silo" / f"entrypoint.silo{n}.sh").read_text(encoding="utf-8")

    block = text[text.index("FED_MONITOR_AUTOSTART"):text.index("tail -f /dev/null")]
    assert f"{WORKER} monitor" in block
    assert "while true" in block and "sleep" in block  # 죽으면 다시 띄운다
    assert '"$FED_CENTRAL"' in block and '"$FED_SILO_ID"' in block


@pytest.mark.unit
@pytest.mark.parametrize("name", ["e2e_phase1.py", "e2e_phase2.py"])
def test_e2e_drivers_use_the_mounted_worker(name):
    text = (SCRIPTS / name).read_text(encoding="utf-8")

    assert "docker cp" not in text
    assert "/tmp/silo_worker.py" not in text
    assert WORKER in text
