"""Flower ServerApp: FedAvg with configurable client count and round hash audit."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import numpy as np
from flwr.app import ArrayRecord, ConfigRecord, Context, Message, MetricRecord
from flwr.serverapp import Grid, ServerApp
from flwr.serverapp.strategy import FedAvg

from flower_silo1.aggregation_util import weighted_aggregate_train
from flower_silo1.config_util import parse_csv_columns
from flower_silo1.task import arrays_to_vector, hash_array_record, init_parameters

app = ServerApp()

_round1_global_hash: str | None = None


def _log(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, sort_keys=True))


def _expected_clients(context: Context) -> int:
    raw = context.run_config.get("expected-clients", 1)
    expected = int(raw)
    if expected < 1:
        raise ValueError("expected-clients must be >= 1")
    return expected


def _aggregate_vectors_allclose(
    manual: ArrayRecord,
    fedavg: ArrayRecord,
    *,
    round_label: str,
) -> None:
    """Assert manual weighted mean matches FedAvg numerically (not by hash)."""
    manual_arr = np.asarray(
        arrays_to_vector(manual.to_numpy_ndarrays()), dtype=np.float64
    )
    fed_arr = np.asarray(
        arrays_to_vector(fedavg.to_numpy_ndarrays()), dtype=np.float64
    )
    if manual_arr.shape != fed_arr.shape:
        raise RuntimeError(
            f"{round_label}: aggregate shape mismatch "
            f"manual={manual_arr.shape} fedavg={fed_arr.shape}"
        )
    if not np.all(np.isfinite(manual_arr)) or not np.all(np.isfinite(fed_arr)):
        raise RuntimeError(f"{round_label}: aggregate contains non-finite values")
    if not np.allclose(
        manual_arr, fed_arr, rtol=1e-9, atol=1e-12, equal_nan=False
    ):
        raise RuntimeError(f"{round_label}: weighted aggregate numeric mismatch")


def _config_str(msg: Message, key: str) -> str | None:
    cfg = msg.content.get("config")
    if cfg is None:
        return None
    value = cfg.get(key)
    if value is None:
        return None
    return str(value)


class SiloFedAvg(FedAvg):
    """FedAvg with per-round audits, N-client gate, and weighted-aggregate check."""

    def __init__(self, *, expected_clients: int, **kwargs: object) -> None:
        super().__init__(**kwargs)
        self.expected_clients = expected_clients

    def configure_train(
        self,
        server_round: int,
        arrays: ArrayRecord,
        config: ConfigRecord,
        grid: Grid,
    ) -> Iterable[Message]:
        global_hash = hash_array_record(arrays)
        _log(
            "server_round_configure",
            round=server_round,
            global_hash=global_hash,
            expected_clients=self.expected_clients,
        )
        if server_round == 2:
            if _round1_global_hash is None:
                raise RuntimeError("round 1 global hash missing before round 2")
            if global_hash != _round1_global_hash:
                raise RuntimeError(
                    "round2 base does not equal round1 result: "
                    f"{global_hash} != {_round1_global_hash}"
                )
            _log("verify_round2_base_equals_round1_result", status="ok")
        return super().configure_train(server_round, arrays, config, grid)

    def aggregate_train(
        self,
        server_round: int,
        replies: Iterable[Message],
    ) -> tuple[ArrayRecord | None, MetricRecord | None]:
        global _round1_global_hash  # noqa: PLW0603
        replies_list = list(replies)
        valid = [msg for msg in replies_list if not msg.has_error()]
        errors = [msg for msg in replies_list if msg.has_error()]
        if errors:
            raise RuntimeError(
                f"round {server_round}: {len(errors)} client error(s), expected 0"
            )
        if len(valid) != self.expected_clients:
            raise RuntimeError(
                f"round {server_round}: expected exactly {self.expected_clients} "
                f"successful replies, got valid={len(valid)} "
                f"total={len(replies_list)}"
            )
        node_ids = {msg.metadata.src_node_id for msg in valid}
        silo_ids = {_config_str(msg, "silo-id") for msg in valid}
        if len(node_ids) != self.expected_clients:
            raise RuntimeError(
                f"round {server_round}: expected {self.expected_clients} distinct "
                f"nodes, got {len(node_ids)}"
            )
        if None in silo_ids or len(silo_ids) != self.expected_clients:
            raise RuntimeError(
                f"round {server_round}: expected {self.expected_clients} distinct "
                f"silo-id values in ConfigRecord, got {silo_ids}"
            )
        for msg in valid:
            received_hash = _config_str(msg, "received-hash")
            local_hash = _config_str(msg, "local-hash")
            metrics = msg.content.get("metrics")
            num_examples = metrics.get("num-examples") if metrics else None
            loss = metrics.get("loss") if metrics else None
            _log(
                "server_round_received",
                round=server_round,
                node_id=msg.metadata.src_node_id,
                silo_id=_config_str(msg, "silo-id"),
                received_hash=received_hash,
                local_hash=local_hash,
                num_examples=num_examples,
                loss=loss,
            )
            if server_round == 2 and _round1_global_hash is not None:
                if received_hash != _round1_global_hash:
                    raise RuntimeError(
                        f"round 2 client {_config_str(msg, 'silo-id')} "
                        f"received_hash {received_hash} != round1 global "
                        f"{_round1_global_hash}"
                    )
        manual_arrays, manual_total = weighted_aggregate_train(valid)
        agg_arrays, agg_metrics = super().aggregate_train(server_round, replies_list)
        if agg_arrays is None:
            raise RuntimeError(f"round {server_round}: aggregation returned no arrays")
        _aggregate_vectors_allclose(
            manual_arrays,
            agg_arrays,
            round_label=f"round {server_round}",
        )
        global_hash = hash_array_record(agg_arrays)
        _log(
            "server_round_global",
            round=server_round,
            global_hash=global_hash,
            weighted_num_examples=manual_total,
            weighted_aggregate_verified=True,
        )
        if server_round == 1:
            _round1_global_hash = global_hash
        if agg_metrics is not None:
            _log(
                "server_round_metrics",
                round=server_round,
                loss=agg_metrics.get("loss"),
                num_examples=agg_metrics.get("num-examples"),
            )
        return agg_arrays, agg_metrics


def _parameter_dim(context: Context) -> int:
    dim = int(context.run_config.get("parameter-dim") or 0)
    if dim > 0:
        expected = len(parse_csv_columns(context.run_config["feature-columns"], "feature-columns")) + 1
        if dim != expected:
            raise ValueError(f"parameter-dim {dim} != feature count + 1 ({expected})")
        return dim
    raise ValueError("parameter-dim must be set in tool.flwr.app.config")


@app.main()
def main(grid: Grid, context: Context) -> None:
    """Run FedAvg rounds with configurable SuperNode count."""
    num_rounds = int(context.run_config["num-server-rounds"])
    expected = _expected_clients(context)
    dim = _parameter_dim(context)
    arrays = ArrayRecord(init_parameters(dim))
    strategy = SiloFedAvg(
        expected_clients=expected,
        fraction_evaluate=0.0,
        min_train_nodes=expected,
        min_evaluate_nodes=0,
        min_available_nodes=expected,
    )
    result = strategy.start(
        grid=grid,
        initial_arrays=arrays,
        num_rounds=num_rounds,
    )
    if context.run_config.get("save-model"):
        out_path = Path(str(context.run_config["model-output-path"]))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        ndarrays = result.arrays.to_numpy_ndarrays()
        np.savez(out_path, *ndarrays)
        _log(
            "saved_final_weights",
            path=str(out_path),
            global_hash=hash_array_record(result.arrays),
        )
