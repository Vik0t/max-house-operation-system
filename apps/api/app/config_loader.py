from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class HouseDefinition(BaseModel):
    id: str
    address: str
    region: str
    management_org: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class ZoneDefinition(BaseModel):
    id: str
    type: str
    number: str | None = None
    name: str
    parent: str | None = None


class AssetDefinition(BaseModel):
    id: str
    zone: str
    type: str
    name: str
    attributes: dict[str, Any] = Field(default_factory=dict)


class RouteDefinition(BaseModel):
    destination: str
    destination_type: str = "management_org"
    action_type: str = "service_request"
    rationale: str
    contractor: str | None = None


class RecurrenceDefinition(BaseModel):
    window_days: int = Field(default=90, ge=1, le=3650)
    count: int = Field(default=3, ge=2, le=100)


class HouseConfig(BaseModel):
    house: HouseDefinition
    zones: list[ZoneDefinition]
    assets: list[AssetDefinition]
    routing: dict[str, RouteDefinition]
    thresholds: dict[str, Any]

    @model_validator(mode="after")
    def validate_references(self):
        zone_ids = {zone.id for zone in self.zones}
        if len(zone_ids) != len(self.zones):
            raise ValueError("Zone IDs must be unique")
        for asset in self.assets:
            if asset.zone not in zone_ids:
                raise ValueError(f"Asset {asset.id} references unknown zone {asset.zone}")
        RecurrenceDefinition.model_validate(self.thresholds.get("recurrence", {}))
        return self

    @property
    def recurrence(self) -> RecurrenceDefinition:
        return RecurrenceDefinition.model_validate(self.thresholds.get("recurrence", {}))


def config_dir() -> Path:
    return Path(__file__).resolve().parents[3] / "configs"


def load_config(path: Path) -> HouseConfig:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return HouseConfig.model_validate(data)


def load_all_configs() -> list[HouseConfig]:
    return [load_config(path) for path in sorted(config_dir().glob("demo_house_*.yaml"))]


def get_house_config(house_id: str) -> HouseConfig:
    for config in load_all_configs():
        if config.house.id == house_id:
            return config
    raise KeyError(f"No configuration for house {house_id}")
