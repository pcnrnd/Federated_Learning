"""사일로 자신의 cgroup v2를 측정한다. 호스트 /proc 사용률로 대체하지 않는다."""
from __future__ import annotations

import os
import time
from pathlib import Path


def own_cgroup(proc: Path = Path("/proc")) -> Path | None:
    """cgroup namespace의 상대 경로와 mount root를 맞춰 자기 cgroup을 찾는다."""
    try:
        group = next(line.split(":", 2)[2] for line in
                     (proc / "self/cgroup").read_text().splitlines() if line.startswith("0::"))
        for line in (proc / "self/mountinfo").read_text().splitlines():
            before, _, after = line.partition(" - ")
            if after.split()[0] != "cgroup2":
                continue
            fields = before.split()
            try:
                relative = Path(group).relative_to(fields[3])
            except ValueError:
                continue
            if ".." in relative.parts:
                continue
            candidate = Path(fields[4]) / relative
            if (candidate / "cpu.stat").exists():
                return candidate
    except (OSError, StopIteration, IndexError):
        pass
    return None


def _capacity(root: Path) -> float:
    quota, period = (root / "cpu.max").read_text().split()
    if quota != "max":
        return int(quota) / int(period)
    try:
        cpuset = (root / "cpuset.cpus.effective").read_text().strip()
    except OSError:
        cpuset = ""
    if cpuset:
        def count(part: str) -> int:
            ends = part.split("-")
            return int(ends[-1]) - int(ends[0]) + 1
        return float(sum(count(part) for part in cpuset.split(",")))
    return float(len(os.sched_getaffinity(0)))


def _usage(root: Path) -> int:
    stats = dict(line.split() for line in (root / "cpu.stat").read_text().splitlines())
    return int(stats["usage_usec"])


def sample_resources(root: Path | None = None, interval: float = 0.25) -> dict:
    """CPU는 cgroup 용량 대비 사용률, 메모리는 유한한 cgroup 한도 대비 사용률.

    디스크 quota/GPU 계측기가 없으면 null과 이유를 보낸다. 공유 파일시스템 전체
    사용률을 사일로 전용 디스크 사용률로 표시하지 않는다.
    """
    root = root if root is not None else own_cgroup()
    result: dict = {
        "cpu_pct": None, "mem_pct": None, "disk_pct": None, "gpu_pct": None,
        "measurement_scope": {},
        "cpu_cores": None, "mem_used_bytes": None, "mem_limit_bytes": None,
        "capabilities": {"disk_pct": False, "gpu_pct": False},
        "unavailable": {
            "disk": "사일로 전용 디스크 quota 계측이 없습니다",
            "gpu": "사일로 GPU 계측기가 없습니다",
        },
    }
    if root is None:
        for metric in ("cpu", "mem"):
            result["unavailable"][metric] = "자기 cgroup v2를 확인할 수 없습니다"
        return result
    try:
        usage_a, start = _usage(root), time.monotonic()
        time.sleep(interval)
        usage_b, end = _usage(root), time.monotonic()
        if end <= start or usage_b < usage_a:
            raise ValueError("CPU 관측 구간 또는 용량이 유효하지 않습니다")
        cores = (usage_b - usage_a) / 1_000_000 / (end - start)
        result["cpu_cores"] = round(cores, 6)
        result["measurement_scope"]["cpu_cores"] = "자기 cgroup v2 CPU 시간 / 관측 시간"
        capacity = _capacity(root)
        if capacity <= 0:
            raise ValueError("CPU 할당량 없음")
        value = 100 * cores / capacity
        result["cpu_pct"] = round(min(100.0, max(0.0, value)), 2)
        result["capabilities"]["cpu_pct"] = True
        result["measurement_scope"]["cpu"] = "자기 cgroup v2 / 할당 CPU 용량"
    except (OSError, ValueError, KeyError, AttributeError) as exc:
        result["unavailable"]["cpu"] = f"cgroup CPU 측정 불가: {type(exc).__name__}"
    try:
        used = int((root / "memory.current").read_text())
        result["mem_used_bytes"] = used
        result["measurement_scope"]["mem_used_bytes"] = "자기 cgroup v2 memory.current"
        maximum = (root / "memory.max").read_text().strip()
        if maximum == "max" or int(maximum) <= 0:
            result["capabilities"]["mem_pct"] = False
            result["unavailable"]["mem"] = "사일로 메모리 한도가 없어 백분율을 계산하지 않습니다"
        else:
            result["mem_limit_bytes"] = int(maximum)
            result["capabilities"]["mem_pct"] = True
            result["mem_pct"] = round(min(100.0, 100.0 * used / int(maximum)), 2)
            result["measurement_scope"]["mem"] = "자기 cgroup v2 / 메모리 한도"
    except (OSError, ValueError) as exc:
        result["unavailable"]["mem"] = f"cgroup 메모리 측정 불가: {type(exc).__name__}"
    return result
