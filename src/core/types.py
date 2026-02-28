from datetime import date, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field


class ExamType(StrEnum):
    CT = "CT"
    PET = "PET"
    RX = "RX"
    BIO = "BIO"
    MRI = "MRI"
    ECHO = "ECHO"
    OTHER = "OTHER"


class Sex(StrEnum):
    M = "M"
    F = "F"
    OTHER = "OTHER"


class SmokingStatus(StrEnum):
    NEVER = "Non-fumeur"
    FORMER = "Ex-fumeur"
    CURRENT = "Fumeur"


# --- Patient ---

class PatientInfo(BaseModel):
    patient_id: str
    age: int
    sex: Sex
    weight_kg: float | None = None
    height_cm: float | None = None
    smoking_status: SmokingStatus | None = None
    main_diagnosis: str | None = None


# --- Timeline ---

class TimelineEntry(BaseModel):
    date: date
    exam_type: ExamType
    result: str
    unit: str | None = None
    reference_range: str | None = None
    notes: str | None = None
    physician: str | None = None


class NoduleEntry(BaseModel):
    date: date
    nodule_id: str
    location: str | None = None
    size_mm: float
    density: str | None = None
    suv_max: float | None = None


class PatientTimeline(BaseModel):
    patient: PatientInfo
    entries: list[TimelineEntry] = Field(default_factory=list)
    nodules: list[NoduleEntry] = Field(default_factory=list)
    raw_data: dict[str, Any] = Field(default_factory=dict)


# --- Images ---

class ImageMetadata(BaseModel):
    file_path: Path
    filename: str
    exam_date: date | None = None
    modality: str | None = None
    width: int | None = None
    height: int | None = None
    thumbnail_b64: str | None = None  # base64 encoded thumbnail


# --- Report ---

class ReportSections(BaseModel):
    indication: str = ""
    technique: str = ""
    parenchyma: str = ""
    mediastinum: str = ""
    pleura: str = ""
    upper_abdomen: str = ""
    comparison: str = ""
    conclusion: str = ""
    recommendations: str = ""


class ReportRequest(BaseModel):
    patient_id: str
    excel_path: Path | None = None
    image_paths: list[Path] = Field(default_factory=list)
    exam_date: date | None = None
    referring_physician: str | None = None
    output_format: str = "pdf"  # "pdf" | "markdown" | "json"


class GeneratedReport(BaseModel):
    patient_id: str
    generated_at: datetime = Field(default_factory=datetime.now)
    sections: ReportSections
    timeline_summary: str = ""
    image_findings: list[str] = Field(default_factory=list)
    output_path: Path | None = None
    pipeline_version: str = "0.1.0"
    tokens_used: int = 0
