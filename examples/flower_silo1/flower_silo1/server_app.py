"""Flower ServerApp: FedAvg (min 1 client), evaluation off, round hash audit."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path

import numpy as np
from flwr.app import ArrayRecord, ConfigRecord, Context, Message, MetricRecord
from flwr.serverapp import Grid, ServerApp
from flwr.serverapp.strategy import FedAvg

from flower_silo1.config_util import parse_csv_columns
from flower_silo1.task import hash_array_record, init_parameters

app = ServerApp()

_round1_global_hash: str | None = None


def _log(event: str, **fields: object) -> None:
    print(json.dumps({"event": event, **fields}, sort_keys=True))


class Silo1FedAvg(FedAvg):
    """FedAvg with per-round parameter hash logging and round-2 base check."""

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
        if len(valid) != 1:
            raise RuntimeError(
                f"round {server_round}: expected exactly 1 successful reply, "
                f"got valid={len(valid)} errors={len(errors)} total={len(replies_list)}"
            )
        msg = valid[0]
        arrays = msg.content.get("arrays")
        metrics = msg.content.get("metrics")
        received_hash = hash_array_record(arrays) if arrays is not None else None
        loss = metrics.get("loss") if metrics is not None else None
        num_examples = metrics.get("num-examples") if metrics is not None else None
        _log(
            "server_round_received",
            round=server_round,
            node_id=msg.metadata.src_node_id,
            received_hash=received_hash,
            num_examples=num_examples,
            loss=loss,
        )
        agg_arrays, agg_metrics = super().aggregate_train(server_round, replies_list)
        if agg_arrays is not None:
            global_hash = hash_array_record(agg_arrays)
            _log(
                "server_round_global",
                round=server_round,
                global_hash=global_hash,
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
    """Run two FedAvg rounds on one SuperNode."""
    num_rounds = int(context.run_config["num-server-rounds"])
    dim = _parameter_dim(context)
    arrays = ArrayRecord(init_parameters(dim))
    strategy = Silo1FedAvg(
        fraction_evaluate=0.0,
        min_train_nodes=1,
        min_evaluate_nodes=0,
        min_available_nodes=1,
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
