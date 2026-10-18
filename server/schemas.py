"""Validated API contracts. Scientific assumptions are explicit in results."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from lz.heptad import assign_register


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Helix(Contract):
    sequence: str = Field(min_length=7, max_length=500)
    offset: int | None = Field(default=None, ge=0, le=6)

    @field_validator("sequence")
    @classmethod
    def clean_sequence(cls, value):
        return assign_register(value).sequence


class TargetRequest(Contract):
    name: str = Field(default="target", min_length=1, max_length=120)
    helix: Helix | None = None
    input_id: str | None = None
    chain: str | None = Field(default=None, max_length=1)

    @model_validator(mode="after")
    def one_source(self):
        if (self.helix is None) == (self.input_id is None):
            raise ValueError("give exactly one of helix or input_id")
        return self


class ScoreRequest(Contract):
    helix1: Helix
    helix2: Helix
    model_id: str = "default"


class ScreenRequest(Contract):
    target_id: str
    model_id: str = "default"
    library_id: str = "default"
    top: int = Field(default=20, ge=1, le=500)


class DesignParameters(Contract):
    length: int | None = Field(default=None, ge=14, le=100)
    offset: int = Field(default=0, ge=0, le=6)
    n_restarts: int = Field(default=8, ge=1, le=32)
    n_steps: int = Field(default=4000, ge=1, le=20000)
    t_start: float = Field(default=1.2, gt=0, le=10)
    t_end: float = Field(default=0.02, gt=0, le=10)
    fixed: dict[int, str] = Field(default_factory=dict)

    @field_validator("fixed")
    @classmethod
    def valid_fixed(cls, values):
        if any(i < 0 or r not in "ACDEFGHIKLMNPQRSTVWY" or len(r) != 1
               for i, r in values.items()):
            raise ValueError("fixed must map nonnegative positions to amino acids")
        return values


class OrthogonalParameters(Contract):
    n_pairs: int = Field(default=2, ge=1, le=4)
    length: int | None = Field(default=None, ge=14, le=100)
    offset: int = Field(default=0, ge=0, le=6)
    n_restarts: int = Field(default=4, ge=1, le=16)
    n_steps: int = Field(default=6000, ge=1, le=20000)
    margin: float = Field(default=3.0, gt=0, le=20)
    t_start: float = Field(default=1.5, gt=0, le=10)
    t_end: float = Field(default=0.03, gt=0, le=10)


class DesignRun(Contract):
    kind: Literal["design"]
    target_id: str
    model_id: str = "default"
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)
    parameters: DesignParameters = Field(default_factory=DesignParameters)


class OrthogonalRun(Contract):
    kind: Literal["orthogonal"]
    target_id: str | None = None
    model_id: str = "default"
    seed: int | None = Field(default=None, ge=0, le=2**63 - 1)
    parameters: OrthogonalParameters = Field(default_factory=OrthogonalParameters)


class StructureRun(Contract):
    kind: Literal["structure", "dockprep"]
    input_id: str
    chain: str | None = Field(default=None, max_length=1)


class CalibrationRun(Contract):
    kind: Literal["calibration"]
    input_id: str


class ExportRun(Contract):
    kind: Literal["export"]
    source_run_id: str


RunRequest = Annotated[
    DesignRun | OrthogonalRun | StructureRun | CalibrationRun | ExportRun,
    Field(discriminator="kind"),
]
