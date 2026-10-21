"""Parse Flower run_config scalars (UserConfigValue: bool|float|int|str only)."""

from __future__ import annotations

from flwr.app.user_config import UserConfigValue


def parse_csv_columns(value: UserConfigValue, label: str) -> list[str]:
    """Split a comma-separated column list from TOML run config."""
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a comma-separated string in pyproject.toml")
    columns = [part.strip() for part in value.split(",") if part.strip()]
    if not columns:
        raise ValueError(f"{label} must list at least one column")
    return columns


def parse_target_column(value: UserConfigValue) -> str:
    """Read the single target column name from run config."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("target-column must be a non-empty string in pyproject.toml")
    return value.strip()
