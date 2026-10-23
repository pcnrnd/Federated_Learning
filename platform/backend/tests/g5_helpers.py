"""배포 저장소/전략 회귀용 Docker 경계 대역. 실제 HTTP 검증은 별도 runtime 시험에서 수행한다."""
from types import SimpleNamespace

from docker.errors import NotFound

from models.packaging_schemas import DeploymentRequest, DeploymentTargetResult, ModelRegisterRequest
from services import deployment_runtime as runtime, deployment_service as service, model_registry

IMAGE = "sha256:" + "a" * 64
IDENTITY = {"model": "actual-model", "version": "1.0.0", "framework": "pytorch", "weights_checksum": "b" * 64}


class Containers:
    def __init__(self, image):
        self.image, self.items, self.creates = image, {}, []

    def get(self, identity):
        for item in self.items.values():
            if identity in (item.id, item.name):
                return item
        raise NotFound("fixture confirmed absent")

    def list(self, **kwargs):
        label = kwargs.get("filters", {}).get("label")
        return [item for item in self.items.values() if not label or
                item.labels.get("fed.deployment_id") == label.partition("=")[2]]

    def create(self, **kwargs):
        self.creates.append(kwargs)
        identity = "container-" + str(len(self.creates))
        item = SimpleNamespace(id=identity, short_id=identity, name=kwargs["name"], labels=kwargs["labels"],
            image=self.image, status="created", reload=lambda: None)
        item.start = lambda: setattr(item, "status", "running")
        item.stop = lambda **_kw: setattr(item, "status", "exited")
        item.remove = lambda **_kw: self.items.pop(identity, None)
        self.items[identity] = item
        return item


def setup_world(tmp_path, monkeypatch):
    from config.server_manager import save_servers
    weights = tmp_path / "fixture-model.pt"
    weights.write_bytes(b"framework boundary fixture; not an actual torch model")
    model = model_registry.register_model(ModelRegisterRequest(name=IDENTITY["model"], version="1.0.0",
        framework="pytorch", weights_path=str(weights)))
    hosts = {node: {"base_url": "tcp://127.0.0.1:2375", "role": "client"} for node in ("silo-1", "silo-2")}
    save_servers(hosts)
    monkeypatch.setattr(service, "refresh_docker_hosts", lambda: None)
    monkeypatch.setattr(service, "get_docker_hosts", lambda: hosts)
    image = SimpleNamespace(id=IMAGE, attrs={"Config": {"Labels": {"fed.weights_checksum": IDENTITY["weights_checksum"]}}})
    clients = {node: SimpleNamespace(images=SimpleNamespace(get=lambda _id: image),
        containers=Containers(image), close=lambda: None) for node in hosts}
    monkeypatch.setattr(service, "get_docker_client", clients.__getitem__)
    monkeypatch.setattr(runtime, "pinned_package", lambda _m, _r: (IMAGE, dict(IDENTITY)))
    monkeypatch.setattr(runtime, "probe_inputs", lambda _m, _r: [[1]])
    verified = []
    failed = set()

    def verify(client, container, node, entry, _model, request, **_kw):
        verified.append((entry.deployment_id, dict(request.env), list(request.target_node_ids), request.inference_port))
        node_id = next(key for key, value in clients.items() if value is client)
        if node_id in failed:
            raise ValueError("fixture endpoint identity mismatch")
        assert container.image.id == entry.expected_image_id and container.status == "running"
        return DeploymentTargetResult(status="running", container_id=container.id, image_id=IMAGE,
            endpoint="http://fixture/"+node_id, weights_checksum=IDENTITY["weights_checksum"],
            prediction_checksum="c"*64, verified_at=service._now_iso())
    monkeypatch.setattr(runtime, "verify_target", verify)
    return SimpleNamespace(model=model, clients=clients, failed=failed, verified=verified)


def request(**updates):
    values = dict(model_name=IDENTITY["model"], version="1.0.0", strategy="realtime",
        target_node_ids=["silo-1", "silo-2"], env={"APP_SETTING": "preserved=value"})
    values.update(updates)
    return DeploymentRequest(**values)
