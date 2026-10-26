"""보존 정제 출력→live ridge→HTTP child hop→중앙 대표 제출 (stdlib)."""
from __future__ import annotations

import hmac
import json
import os
import signal
import socket
import threading
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import training_protocol as protocol
from .cleaning_output import load_output
from .client import SiloClient, SiloClientError
from .iterative_ridge import train_iterative_ridge


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".pending")
    with temporary.open("wb") as stream:
        stream.write(protocol.encoded(value))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    if os.name != "nt":
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)


@contextmanager
def local_lock(data_dir):
    """프로세스 중단으로 자동 해제되는 OS lock; 재시작 때 stale marker 제거 불필요."""
    root = Path(data_dir) / ".training"
    root.mkdir(parents=True, exist_ok=True)
    with (root / ".lock").open("a+b") as stream:
        if os.name == "nt":
            import msvcrt
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl
            fcntl.flock(stream, fcntl.LOCK_EX)
        try:
            yield root
        finally:
            if os.name == "nt":
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def train_own_leaf(entry, silo_id, data_dir):
    """보존 정제 출력(ID·해시 검증)으로 로컬 ridge를 학습해 원기여 1건을 만든다.

    자체 엔진(LiveWorker)과 Flower ClientApp이 같은 함수를 쓴다. 해시가 다르면 load_output이
    ValueError를 내고 학습하지 않는다.
    """
    reference = entry["cleaning_snapshot"][silo_id]
    rows, manifest = load_output(data_dir, reference)
    if manifest["silo_id"] != silo_id or manifest["job_id"] != entry["cleaning_job_id"]:
        raise ValueError("정제 출력의 실제 사일로/작업 불일치")
    settings = entry["learning"]
    result = train_iterative_ridge(rows, settings["features"], settings["target"],
        initial_parameters=entry["base_parameters"], l2=settings["l2"],
        step_size=settings["step_size"], steps=settings["steps"])
    return protocol.make_leaf(entry, silo_id, result)


class LiveWorker:
    def __init__(self, client: SiloClient, data_dir: str):
        self.client, self.data_dir = client, data_dir

    @staticmethod
    def round_path(root, identity):
        return root / protocol.digest(identity)

    def attempt_round(self, entry):
        try:
            return self.process_round(entry)
        except (FileNotFoundError, ValueError) as exc:
            try:
                self.client.report_training_failure(entry["round_id"],
                    "input_missing" if isinstance(exc, FileNotFoundError) else "invalid_model_or_input")
            except (OSError, SiloClientError):
                pass  # 중앙 복구 후 같은 오류 재보고. 원시 행/경로/상세 본문은 전송하지 않는다.
            raise

    def receive(self, sender, leaf, peer_ip):
        entry = self.client.get_round(leaf["round_id"])
        protocol.validate_round(entry)
        if (entry.get("learning") is None or sender != leaf.get("silo_id")
                or sender not in (entry.get("cluster_snapshot") or {}).get(self.client.silo_id, [])):
            raise ValueError("라운드의 수신 집계자/하위 참여 스냅샷과 다릅니다")
        # 본문 ID만으로 발신자를 승인하지 않는다. 고정 worker 주소의 실제 peer와 대조한다.
        host = urllib.parse.urlparse(entry["transport_snapshot"][sender]).hostname
        addresses = {item[4][0] for item in socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)}
        if peer_ip not in addresses:
            raise PermissionError("발신 peer가 고정 worker 주소와 다릅니다")
        protocol.validate_leaf(entry, leaf)
        with local_lock(self.data_dir) as root:
            path = self.round_path(root, entry["round_id"]) / "inbox" / f"{protocol.digest(sender)}.json"
            if path.exists():
                previous = json.loads(path.read_bytes())
                if previous["leaf"] != leaf:
                    raise ValueError("같은 sender의 다른 원기여는 덮어쓸 수 없습니다")
                return previous["ack"]
            if entry["status"] != "open":
                raise ValueError("마감된 라운드의 새 원기여")
            ack = {"round_id": entry["round_id"], "sender": sender, "receiver": self.client.silo_id,
                   "contribution_id": leaf["contribution_id"], "checksum": leaf["checksum"],
                   "received_at": timestamp()}
            atomic_json(path, {"leaf": leaf, "ack": ack})  # 내구 수신 뒤에만 ACK.
            return ack

    def send(self, endpoint, leaf):
        sender = self.client.silo_id
        request = urllib.request.Request(endpoint.rstrip("/") + "/api/worker/contributions/"
            + urllib.parse.quote(sender, safe=""), data=protocol.encoded(leaf), method="POST",
            headers={"Content-Type": "application/json", "X-FED-Silo-ID": sender})
        if self.client.api_key:
            request.add_header("X-FED-API-Key", self.client.api_key)
        with urllib.request.urlopen(request, timeout=self.client.timeout) as response:
            ack = json.loads(response.read(1024 * 1024))
        if (ack.get("contribution_id") != leaf["contribution_id"] or ack.get("checksum") != leaf["checksum"]
                or ack.get("sender") != sender or ack.get("round_id") != leaf["round_id"]):
            raise ValueError("HTTP 수신 ACK 무결성 불일치")
        return ack

    def process_round(self, entry):
        silo_id = self.client.silo_id
        if entry.get("learning") is None or silo_id not in protocol.participants(entry):
            return False
        protocol.validate_round(entry)
        with local_lock(self.data_dir) as root:
            path = self.round_path(root, entry["round_id"])
            own_path = path / "own.json"  # 내구 own-result이자 재전송 outbox.
            if own_path.exists():
                own = json.loads(own_path.read_bytes())
                protocol.validate_leaf(entry, own)
            else:
                own = train_own_leaf(entry, silo_id, self.data_dir)
                atomic_json(own_path, own)
            parents = [node for node, children in entry["cluster_snapshot"].items() if silo_id in children]
            if parents:
                ack_path = path / "parent_ack.json"
                if not ack_path.exists():
                    ack = self.send(entry["transport_snapshot"][parents[0]], own)
                    atomic_json(ack_path, ack)
                ack = json.loads(ack_path.read_bytes())
                if (ack.get("receiver") != parents[0] or ack.get("sender") != silo_id
                        or ack.get("round_id") != entry["round_id"] or ack.get("checksum") != own["checksum"]
                        or ack.get("contribution_id") != own["contribution_id"]):
                    raise ValueError("보존 ACK와 라운드/원기여/상위 불일치")
                return True
            ack_path = path / "central_ack.json"
            leaves = [own]
            for child in entry["cluster_snapshot"].get(silo_id, []):
                inbox = path / "inbox" / f"{protocol.digest(child)}.json"
                if not inbox.exists():
                    return False
                leaves.append(json.loads(inbox.read_bytes())["leaf"])
            envelope = protocol.combine_live(entry, silo_id, leaves)
            if ack_path.exists():
                if json.loads(ack_path.read_bytes()).get("envelope_checksum") != envelope["envelope_checksum"]:
                    raise ValueError("보존 중앙 ACK와 대표 원기여 불일치")
                return True
            atomic_json(path / "envelope.json", envelope)
            ack = self.client.push_live_parameters(envelope)
            if ack.get("envelope_checksum") != envelope["envelope_checksum"]:
                raise ValueError("중앙 대표 기여 ACK 불일치")
            atomic_json(ack_path, {"envelope_checksum": envelope["envelope_checksum"],
                                   "acknowledged_at": timestamp(), "record": ack})
            return True


def make_server(worker, address):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass  # 원시 요청 본문·키·행을 로그에 남기지 않는다.

        def do_POST(self):
            try:
                if worker.client.api_key and not hmac.compare_digest(
                        self.headers.get("X-FED-API-Key", ""), worker.client.api_key):
                    self.respond(401, {"error": "unauthorized"})
                    return
                prefix = "/api/worker/contributions/"
                if not self.path.startswith(prefix) or "/" in self.path[len(prefix):]:
                    self.respond(404, {"error": "unknown route"})
                    return
                sender = urllib.parse.unquote(self.path[len(prefix):])
                if self.headers.get("X-FED-Silo-ID") != sender:
                    raise ValueError("URL/header sender 불일치")
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 2 * 1024 * 1024:
                    raise ValueError("기여 크기 제한")
                leaf = json.loads(self.rfile.read(size))
                self.respond(200, worker.receive(sender, leaf, self.client_address[0]))
            except PermissionError:
                self.respond(403, {"error": "peer mismatch"})
            except (ValueError, KeyError, TypeError):
                self.respond(422, {"error": "invalid contribution"})
            except SiloClientError as exc:
                status = exc.status if 400 <= exc.status < 500 else 503
                self.respond(status, {"error": "metadata request failed"})
            except OSError:
                self.respond(503, {"error": "metadata temporarily unavailable"})

        def respond(self, status, payload):
            body = protocol.encoded(payload)
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
    server = ThreadingHTTPServer(address, Handler)
    server.daemon_threads = True
    return server


def run(client, data_dir, host="0.0.0.0", port=8081, poll_interval=2):
    worker = LiveWorker(client, data_dir)
    server = make_server(worker, (host, port))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    stopping = threading.Event()
    previous = {sig: signal.signal(sig, lambda *_: stopping.set()) for sig in (signal.SIGTERM, signal.SIGINT)}
    thread.start()
    try:
        while not stopping.is_set():
            try:
                entries = client.list_rounds(status="open")
                for entry in entries:
                    if stopping.is_set():
                        break
                    try:
                        worker.attempt_round(entry)
                    except (ValueError, OSError, SiloClientError) as exc:
                        print(json.dumps({"event": "live_training_error", "silo_id": client.silo_id,
                            "round_id": entry["round_id"], "error_type": type(exc).__name__}), flush=True)
            except (OSError, SiloClientError):
                pass
            stopping.wait(max(0.05, poll_interval))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
        for sig, handler in previous.items():
            signal.signal(sig, handler)
