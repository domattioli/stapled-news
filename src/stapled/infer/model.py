"""Data models for inference."""

from dataclasses import dataclass
from typing import Optional


@dataclass
class TruthState:
    """Represents a latent truth state."""

    state: int  # binary: 0 or 1
    magnitude_bucket: Optional[int] = None  # ordinal: 0, 1, 2, ...


@dataclass
class OutletParams:
    """Estimated outlet parameters."""

    reliability: float  # [0, 1]
    bias: float  # [-1, 1]
    calibration: float  # > 0


@dataclass
class RunConfig:
    """EM run configuration."""

    max_iter: int = 200
    tol: float = 1e-6
    restarts: int = 5
    concentration_threshold: float = 0.9
