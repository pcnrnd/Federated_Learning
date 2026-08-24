"""PoC 백엔드 핵심 비즈니스 로직 및 알고리즘 서비스 레이어
(Docker SDK 연동 및 FedAvg 파라미터 집계 모듈)
"""
from __future__ import annotations

import os
from pathlib import Path
import yaml
import docker
from models import ServerConfig


class DockerService:
    """원격 노드/사일로 탐색 및 컨테이너 상태 라이프사이클 제어 서비스"""

    def __init__(self, config_path: Path):
        self.config_path = config_path
        self._ensure_config_exists()

    def _ensure_config_exists(self):
        """설정 파일 디렉토리 및 초기 yaml 구성 자동 생성"""
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            default_config = {
                "main": {
                    "base_url": "unix://var/run/docker.sock",
                    "label": "중앙 로컬 서버",
                    "type": "local",
                    "role": "central",
                    "tls": False
                },
                "silo_1": {
                    "base_url": "tcp://localhost:2371",
                    "label": "의료 사일로 A",
                    "type": "remote",
                    "role": "client",
                    "tls": False
                },
                "silo_2": {
                    "base_url": "tcp://localhost:2372",
                    "label": "바이오 사일로 B",
                    "type": "remote",
                    "role": "client",
                    "tls": False
                }
            }
            self.save_servers(default_config)

    def load_servers(self) -> dict:
        """servers.yaml 파싱"""
        with open(self.config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}

    def save_servers(self, data: dict):
        """servers.yaml 영속 저장"""
        with open(self.config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f, allow_unicode=True)

    def get_docker_client(self, base_url: str) -> docker.DockerClient | None:
        """Docker SDK Client 동적 생성"""
        try:
            return docker.DockerClient(base_url=base_url, timeout=5)
        except Exception as e:
            print(f"Docker Client 연결 실패 ({base_url}): {e}")
            return None

    def test_connection(self, base_url: str) -> bool:
        """노드 Docker API ping 테스트"""
        client = self.get_docker_client(base_url)
        if not client:
            return False
        try:
            client.ping()
            return True
        except Exception:
            return False
        finally:
            if client:
                client.close()

    def list_containers(self, node_id: str) -> list[dict]:
        """특정 노드의 실시간 컨테이너 상태 수집"""
        servers = self.load_servers()
        if node_id not in servers:
            raise ValueError(f"존재하지 않는 노드 ID: {node_id}")

        base_url = servers[node_id]["base_url"]
        client = self.get_docker_client(base_url)
        if not client:
            return []

        try:
            containers = client.containers.list(all=True)
            return [
                {
                    "container_id": c.short_id,
                    "name": c.name,
                    "image": c.image.tags[0] if c.image.tags else "unknown",
                    "status": c.status,
                    "state": c.attrs.get("State", {})
                }
                for c in containers
            ]
        except Exception as e:
            print(f"컨테이너 조회 실패 ({node_id}): {e}")
            return []
        finally:
            if client:
                client.close()

    def control_container(self, node_id: str, container_id: str, action: str) -> bool:
        """사일로 컨테이너 라이프사이클 원격 제어 (Start/Stop/Restart)"""
        servers = self.load_servers()
        if node_id not in servers:
            raise ValueError(f"존재하지 않는 노드 ID: {node_id}")

        base_url = servers[node_id]["base_url"]
        client = self.get_docker_client(base_url)
        if not client:
            return False

        try:
            container = client.containers.get(container_id)
            if action == "start":
                container.start()
            elif action == "stop":
                container.stop()
            elif action == "restart":
                container.restart()
            return True
        except Exception as e:
            print(f"컨테이너 제어 실패 ({node_id} / {container_id}): {e}")
            return False
        finally:
            if client:
                client.close()


class FederatedService:
    """FedAvg 알고리즘 연합 가중치 취합 연산 서비스"""

    @staticmethod
    def aggregate_fedavg(payloads: list[dict]) -> dict[str, float]:
        """FedAvg (Federated Averaging) 파라미터 집계 처리
        수식: W_global = Sum( (n_k / N) * W_k )
        """
        if not payloads:
            raise ValueError("수집된 로컬 가중치 데이터가 비어 있습니다.")

        total_samples = sum(payload["sample_size"] for payload in payloads)
        if total_samples == 0:
            raise ValueError("총 데이터 샘플 수가 0입니다. 집계를 수행할 수 없습니다.")

        global_weights = {}
        # 첫 번째 가중치 구조의 키들을 기준으로 루프
        first_payload = payloads[0]["weights"]
        for key in first_payload.keys():
            weighted_sum = 0.0
            for payload in payloads:
                local_weights = payload["weights"]
                sample_size = payload["sample_size"]
                
                # 특정 사일로에 해당 레이어 가중치 키가 누락되었을 경우에 대한 방어 코드
                val = local_weights.get(key, 0.0)
                
                # 가중치 팩터 (n_k / N) 곱하여 누적
                weight_factor = sample_size / total_samples
                weighted_sum += val * weight_factor
                
            global_weights[key] = round(weighted_sum, 6)

        return global_weights
