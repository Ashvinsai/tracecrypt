"""Application-owned interoperability contract, NOT an official NCRP API schema."""
from __future__ import annotations
import datetime as dt
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

Allegation = Literal["investment_scam", "task_fraud", "sextortion", "ransomware", "phishing", "darknet", "organized_financial_crime", "other"]
Source = Literal["manual", "agency_gateway", "ncrp_gateway", "sahyog_gateway", "vasp_gateway"]


class WalletReport(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    network_key: Literal["tron", "ethereum", "bsc", "base"]
    address: str = Field(min_length=1, max_length=128)
    token_contract: str | None = Field(default=None, min_length=1, max_length=128)
    seed_event_reference: str | None = Field(default=None, min_length=1, max_length=256)


class ComplaintPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    schema_version: Literal["1.0"] = "1.0"
    external_reference: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9._:/-]+$")
    title: str = Field(min_length=1, max_length=300)
    allegation_type: Allegation = "other"
    wallets: list[WalletReport] = Field(min_length=1, max_length=20)
    incident_start: dt.datetime | None = None
    analysis_cutoff: dt.datetime | None = None
    # Deliberately no victim names, passwords, private keys, screenshots or bank
    # statements. Store sensitive complaint attachments in the agency system.

    @field_validator("incident_start", "analysis_cutoff")
    @classmethod
    def aware(cls, value):
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("timestamps must include a timezone")
            return value.astimezone(dt.UTC)
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.incident_start and self.analysis_cutoff and self.incident_start > self.analysis_cutoff:
            raise ValueError("incident_start must not exceed analysis_cutoff")
        return self
