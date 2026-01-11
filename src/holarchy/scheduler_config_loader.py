from dataclasses import dataclass
from tomllib import load
from typing import Any


@dataclass
class ScheduledJobConfig:
    name: str
    blueprint: str
    input_data: dict[str, Any]
    interval_seconds: int | None = None
    daily_at: str | None = None
    weekly_days: list[str] | None = None
    monthly_dates: list[int] | None = None
    time: str | None = None


def load_schedules_from_file(file_path: str) -> list[ScheduledJobConfig]:
    """Loads scheduled job configurations from a TOML file."""
    with open(file_path, "rb") as f:
        data = load(f)

    schedules = []
    for name, config in data.items():
        # Skip sections that might be metadata (though TOML structure usually implies all top-level keys are jobs)
        if not isinstance(config, dict):
            continue

        schedules.append(
            ScheduledJobConfig(
                name=name,
                blueprint=config.get("blueprint"),
                input_data=config.get("input_data", {}),
                interval_seconds=config.get("interval_seconds"),
                daily_at=config.get("daily_at"),
                weekly_days=config.get("weekly_days"),
                monthly_dates=config.get("monthly_dates"),
                time=config.get("time"),
            )
        )
    return schedules
