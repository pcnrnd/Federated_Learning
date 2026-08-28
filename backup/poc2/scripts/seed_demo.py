"""Seed a running local app with dashboard demo data.

Run after starting uvicorn:
    python scripts/seed_demo.py --base-url http://127.0.0.1:8010
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

APP_DIR = Path(__file__).resolve().parents[1]
REPO_DIR = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

MODEL_NAME = "demo-alpha"
MODEL_VERSION = "1.0.0"
GROUP_ID = "demo-six-silos"
DEPLOYMENT_ID = "demo-alpha-realtime"


def _request(
    method: str,
    base_url: str,
    path: str,
    body: dict[str, Any] | None = None,
    *,
    allow_conflict: bool = False,
) -> dict[str, Any]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(f"{base_url.rstrip('/')}{path}", data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        if allow_conflict and exc.code == 409:
            return {"ok": True, "conflict": True}
        body_text = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {path} failed: HTTP {exc.code} {body_text}") from exc


def _configure_config_dir(config_dir: Path | None) -> None:
    if config_dir is not None:
        os.environ["FED_CONFIG_DIR"] = str(config_dir.resolve())


def _reset_demo_config(config_dir: Path) -> None:
    target = config_dir.resolve()
    if not target.is_relative_to(REPO_DIR.resolve()) or "demo" not in target.name:
        raise SystemExit(f"데모 config만 reset할 수 있습니다: {target}")
    target.mkdir(parents=True, exist_ok=True)
    for path in target.glob("*.yaml"):
        path.unlink()
    for path in target.glob("*.log"):
        path.unlink()


def _seed_servers() -> None:
    from config.server_manager import load_servers, save_servers

    servers = load_servers()
    servers.setdefault(
        "main",
        {
            "base_url": "unix://var/run/docker.sock",
            "label": "중앙 서버",
            "type": "local",
            "role": "central",
            "tls": False,
        },
    )
    for i in range(1, 7):
        servers[f"silo-{i}"] = {
            "base_url": f"tcp://localhost:{2370 + i}",
            "label": f"데모 사일로 {i}",
            "type": "remote",
            "role": "client",
            "tls": False,
        }
    save_servers(servers)


def _seed_deployment() -> None:
    from config.registry_manager import DEPLOYMENTS_FILE, load_deployments, save_deployments

    deployments = load_deployments()
    deployments[DEPLOYMENT_ID] = {
        "deployment_id": DEPLOYMENT_ID,
        "model_name": MODEL_NAME,
        "version": MODEL_VERSION,
        "image_tag": f"fed-model-{MODEL_NAME}:{MODEL_VERSION}",
        "strategy": "realtime",
        "target_node_ids": [f"silo-{i}" for i in range(1, 7)],
        "container_map": {f"silo-{i}": f"demo-container-{i}" for i in range(1, 7)},
        "status": "running",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "previous_deployment_id": None,
        "error": None,
    }
    save_deployments(deployments)
    print(f"seeded {DEPLOYMENTS_FILE}")


def _seed_api(base_url: str) -> None:
    weights_path = str(APP_DIR / "demo" / "weights" / "demo-alpha.pt")
    _request(
        "POST",
        base_url,
        "/api/models",
        {
            "name": MODEL_NAME,
            "version": MODEL_VERSION,
            "framework": "pytorch",
            "weights_path": weights_path,
            "input_schema": {"features": "float[]"},
            "output_schema": {"score": "float"},
            "metadata": {"source": "scripts/seed_demo.py"},
        },
        allow_conflict=True,
    )
    group_payload = {
        "group_id": GROUP_ID,
        "description": "데모용 6개 사일로 그룹",
        "member_node_ids": [f"silo-{i}" for i in range(1, 7)],
        "tags": ["demo", "six-silos"],
        "metadata": {"seeded_by": "scripts/seed_demo.py"},
    }
    created = _request(
        "POST",
        base_url,
        "/api/silo-groups",
        group_payload,
        allow_conflict=True,
    )
    if created.get("conflict"):
        _request("PUT", base_url, f"/api/silo-groups/{GROUP_ID}", group_payload)

    _request(
        "POST",
        base_url,
        "/api/monitoring/baselines",
        {
            "model_name": MODEL_NAME,
            "version": MODEL_VERSION,
            "feature": "age",
            "bin_edges": [0, 20, 40, 60, 80, 100],
            "bin_counts": [12, 28, 35, 20, 5],
        },
    )

    now = datetime.now(timezone.utc).replace(microsecond=0)
    for silo_idx in range(1, 7):
        silo_id = f"silo-{silo_idx}"
        for offset in range(6):
            ts = (now - timedelta(minutes=5 * (5 - offset))).isoformat()
            _request(
                "POST",
                base_url,
                "/api/monitoring/metrics",
                {
                    "node_id": silo_id,
                    "model_name": MODEL_NAME,
                    "version": MODEL_VERSION,
                    "metric": "accuracy",
                    "value": round(0.78 + silo_idx * 0.015 + offset * 0.006, 4),
                    "timestamp": ts,
                },
            )
            _request(
                "POST",
                base_url,
                "/api/monitoring/metrics",
                {
                    "node_id": silo_id,
                    "model_name": MODEL_NAME,
                    "version": MODEL_VERSION,
                    "metric": "latency_ms",
                    "value": round(135 - silo_idx * 4 - offset * 1.5, 2),
                    "timestamp": ts,
                },
            )
            _request(
                "POST",
                base_url,
                "/api/monitoring/metrics",
                {
                    "node_id": silo_id,
                    "model_name": MODEL_NAME,
                    "version": MODEL_VERSION,
                    "metric": "throughput_rps",
                    "value": round(48 + silo_idx * 3 + offset * 1.2, 2),
                    "timestamp": ts,
                },
            )
        _request(
            "POST",
            base_url,
            "/api/resources/samples",
            {
                "silo_id": silo_id,
                "cpu_pct": 25 + silo_idx * 6,
                "mem_pct": 32 + silo_idx * 4,
                "gpu_pct": 10 + silo_idx * 7,
                "disk_pct": 40 + silo_idx * 3,
                "timestamp": now.isoformat(),
            },
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed demo data for /dashboard")
    parser.add_argument("--base-url", default="http://127.0.0.1:8010")
    parser.add_argument(
        "--config-dir",
        type=Path,
        default=None,
        help="YAML config directory. Overrides FED_CONFIG_DIR for this process.",
    )
    parser.add_argument(
        "--demo-config",
        action="store_true",
        help="Use repo-local config.demo instead of config.",
    )
    parser.add_argument(
        "--reset-demo",
        action="store_true",
        help="Clear existing YAML/log files in the selected demo config directory before seeding.",
    )
    args = parser.parse_args()

    config_dir = args.config_dir
    if args.demo_config and config_dir is None:
        config_dir = REPO_DIR / "config.demo"
    if args.reset_demo and config_dir is None:
        config_dir = REPO_DIR / "config.demo"
    _configure_config_dir(config_dir)
    if args.reset_demo:
        _reset_demo_config(config_dir or REPO_DIR / "config.demo")

    _seed_servers()
    _seed_deployment()
    try:
        _request("GET", args.base_url, "/healthz")
    except Exception as exc:
        raise SystemExit(
            f"API 서버에 연결할 수 없습니다: {args.base_url} ({exc})\n"
            "먼저 uvicorn을 실행한 뒤 다시 시도하세요."
        ) from exc
    _seed_api(args.base_url)
    print(f"demo ready: {args.base_url}/dashboard")
    print(f"model={MODEL_NAME} version={MODEL_VERSION} feature=age")


if __name__ == "__main__":
    main()
