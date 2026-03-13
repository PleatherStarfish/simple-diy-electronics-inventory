from __future__ import annotations

from enum import StrEnum


class ContainerType(StrEnum):
    GRID_BOX = "grid_box"
    BINDER = "binder"
    DRAWER = "drawer"
    BIN = "bin"


class SlotType(StrEnum):
    GRID_REGION = "grid_region"
    CARD = "card"
    SLOT = "slot"
    BULK = "bulk"


class PackagingType(StrEnum):
    CUT_TAPE = "cut_tape"
    LOOSE = "loose"
    TUBE = "tube"
    REEL = "reel"
    ANTI_STATIC_BAG = "anti_static_bag"
    BULLDOG_CLIPPED_BAG = "bulldog_clipped_bag"
    OTHER = "other"


class StockStatus(StrEnum):
    ACTIVE = "active"
    RESERVED = "reserved"
    CONSUMED = "consumed"


class BuildStatus(StrEnum):
    PLANNED = "planned"
    PARTS_PULLED = "parts_pulled"
    BUILT = "built"
    DEBUG = "debug"
    DONE = "done"
