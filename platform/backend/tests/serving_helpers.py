"""실제 다른 ridge 가중치/HTTP fixture. Docker 객체만 경계 대역이며 입력은 기록하지 않는다."""
from copy import deepcopy
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
from types import SimpleNamespace

from docker.errors import NotFound

from models.packaging_schemas import DeploymentEntry, DeploymentRequest, DeploymentTargetResult, ModelRegisterRequest
from services import deployment_service, model_registry, ridge_artifacts
from silo_sdk import training_protocol as wire


def changed_result(source, offset=2):
    result = deepcopy(source)
    result["round_id"] = "round-different-weights-"+str(offset)
    result["parameters"][-1] += offset
    result["checksum"] = wire.parameter_checksum(result["parameters"])
    for leaf in result["origins"]:
        leaf.pop("contribution_id")
        leaf.update(round_id=result["round_id"], parameters=result["parameters"].copy(), checksum=result["checksum"])
        leaf["contribution_id"] = wire.digest(leaf)
    result["result_id"] = wire.digest(dict(round_id=result["round_id"], checksum=result["checksum"], samples=result["total_samples"],
        origins=sorted(leaf["contribution_id"] for leaf in result["origins"])))
    return result


def server(artifact, model, faults, received, entered, resume):
    identity = dict(model=model.name, version=model.version, framework="ridge", weights_checksum=artifact.weights_sha256,
        artifact_id=artifact.artifact_id, manifest_checksum=artifact.manifest_sha256,
        result_id=artifact.manifest["source_result"]["result_id"])
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def send(self, value, status=200):
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            try:
                self.wfile.write(json.dumps(value).encode())
            except (BrokenPipeError, ConnectionResetError):
                pass

        def do_GET(self):
            self.send(dict(status="ok", **identity), 503 if faults.get("health") else 200)

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            received.append(dict(version=model.version, request_id=body.get("request_id"),
                transient_input_hash=hashlib.sha256(json.dumps(body["inputs"]).encode()).hexdigest()))
            if faults.get("block"):
                entered.set()
                resume.wait(4)
            if faults.get("predict"):
                self.send({"detail": "fixture model failed"}, 503)
                return
            actual = dict(identity)
            if faults.get("identity"):
                actual["version"] = "wrong"
            predictions = ridge_artifacts.predict(artifact, body["inputs"])
            if faults.get("shape"):
                predictions = [[value, value] for value in predictions]
            self.send(dict(ok=True, input_count=len(body["inputs"]), request_id=body.get("request_id"),
                predictions=predictions, **actual))
    http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=http.serve_forever, daemon=True)
    thread.start()
    return http, thread, identity


def setup(tmp_path, monkeypatch, completed_result, versions=2):
    from config.server_manager import save_servers
    servers, containers, models, received, faults, entries, images, ports = [], {}, {}, [], {}, [], {}, {}
    entered, resume = threading.Event(), threading.Event()
    results = [completed_result]+[changed_result(completed_result, index*2) for index in range(1, versions)]
    for index, result in enumerate(results):
        version = "1.0."+str(index)
        artifact = ridge_artifacts.save_artifact(tmp_path / "artifacts", result, version=version)
        model = model_registry.register_model(ModelRegisterRequest(name="model", version=version, framework="ridge",
            weights_path=str(artifact.weights_path)))
        models[version] = model
        faults[version] = {}
        http, thread, identity = server(artifact, model, faults[version], received, entered, resume)
        servers.append((http, thread))
        image = "sha256:"+str(index+1)*64
        deployment_id = ("primary", "shadow", "current")[index]
        container_id = "container-"+deployment_id
        endpoint = f"http://127.0.0.1:{http.server_port}"
        images[image] = SimpleNamespace(id=image, attrs={"Config": {"Labels": {
            "fed.weights_checksum": artifact.weights_sha256, "fed.artifact_id": artifact.artifact_id,
            "fed.manifest_checksum": artifact.manifest_sha256}}})
        ports[image] = http.server_port
        container = SimpleNamespace(id=container_id, image=SimpleNamespace(id=image), status="running", reload=lambda: None,
            labels={"fed.deployment_id": deployment_id}, attrs={"NetworkSettings": {"Ports": {
                "8501/tcp": [{"HostIp": "0.0.0.0", "HostPort": str(http.server_port)}]}}})
        container.stop = lambda _c=container, **_kw: setattr(_c, "status", "exited")
        container.remove = lambda _id=container_id, **_kw: containers.pop(_id, None)
        containers[container_id] = container
        container.name = "fixture-"+deployment_id
        container.start = lambda _c=container: setattr(_c, "status", "running")
        entry = DeploymentEntry(deployment_id=deployment_id, model_name="model", version=version, image_tag=image,
            strategy="realtime", target_node_ids=["silo-1"], container_map={"silo-1": container_id}, status="running",
            created_at=deployment_service._now_iso(), verified_at=deployment_service._now_iso(), expected_image_id=image,
            expected_identity=identity, configuration=DeploymentRequest(model_name="model", version=version,
                strategy="realtime", target_node_ids=["silo-1"]),
            target_results={"silo-1": DeploymentTargetResult(status="running", container_id=container_id, image_id=image,
                endpoint=endpoint, verified_at=deployment_service._now_iso())})
        deployment_service._save(entry)
        entries.append(entry)
    def get(identity):
        for container in containers.values():
            if identity in (container.id, container.name):
                return container
        raise NotFound("fixture absent")
    creates = []
    def create(**kwargs):
        creates.append(kwargs)
        identity = "container-created-"+str(len(creates))
        image = images[kwargs["image"]]
        container = SimpleNamespace(id=identity, short_id=identity, name=kwargs["name"], labels=kwargs["labels"],
            image=image, status="created", reload=lambda: None, attrs={"NetworkSettings": {"Ports": {
                key: [{"HostIp": "0.0.0.0", "HostPort": str(ports[image.id])}] for key in kwargs["ports"]}}})
        container.start = lambda: setattr(container, "status", "running")
        container.stop = lambda **_kw: setattr(container, "status", "exited")
        container.remove = lambda **_kw: containers.pop(identity, None)
        containers[identity] = container
        return container
    client = SimpleNamespace(images=SimpleNamespace(get=images.__getitem__), containers=SimpleNamespace(get=get, create=create, list=lambda **kw: [value for value in containers.values()
        if value.labels["fed.deployment_id"] == kw["filters"]["label"].partition("=")[2]]), close=lambda: None)
    hosts = {"silo-1": {"base_url": "tcp://127.0.0.1:2375", "role": "client"}}
    save_servers(hosts)
    monkeypatch.setattr(deployment_service, "refresh_docker_hosts", lambda: None)
    monkeypatch.setattr(deployment_service, "get_docker_hosts", lambda: hosts)
    monkeypatch.setattr(deployment_service, "get_docker_client", lambda _node: client)
    return SimpleNamespace(entries=entries, faults=faults, received=received, servers=servers, models=models,
        entered=entered, resume=resume, containers=containers)
