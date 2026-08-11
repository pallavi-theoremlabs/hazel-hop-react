from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


class DevCaseCreate(BaseModel):
    case_id: str = Field(min_length=1, max_length=80)
    legal_name: str = Field(min_length=1, max_length=200)
    fdic_certificate_number: str = Field(min_length=1, max_length=40)
    website: str = Field(min_length=1, max_length=500)
    institution_type: str = Field(min_length=1, max_length=100)
    primary_applicant_email: str = Field(min_length=3, max_length=320)


class DevClarificationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_text: str = Field(min_length=1, max_length=10000)
    due_at: str = Field(min_length=1, max_length=80)
    document_required: bool = False
    document_label: Optional[str] = Field(default=None, max_length=300)
    replacement_of_hazel_document_id: Optional[int] = None

    @field_validator("request_text", "due_at", "document_label")
    @classmethod
    def trim_clarification_fields(cls, value: Optional[str]) -> Optional[str]:
        return value.strip() if isinstance(value, str) else value


class ClarificationDraftUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    response: str = Field(default="", max_length=20000)


class SubmitInterestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_name: str = Field(min_length=1, max_length=200)
    fdic_certificate_number: str = Field(min_length=1, max_length=10)
    website: str = Field(min_length=1, max_length=500)
    institution_type: str = Field(min_length=1, max_length=100)
    contact_name: str = Field(min_length=1, max_length=200)
    contact_title: str = Field(min_length=1, max_length=200)
    contact_email: str = Field(min_length=3, max_length=320)
    phone: str = Field(min_length=1, max_length=80)
    reason_for_interest: str = Field(default="", max_length=4000)

    @field_validator("fdic_certificate_number")
    @classmethod
    def validate_fdic_certificate_number(cls, value: str) -> str:
        value = value.strip()
        if not value.isdigit():
            raise ValueError("FDIC certificate number must contain digits only")
        return value

    @field_validator(
        "legal_name",
        "website",
        "institution_type",
        "contact_name",
        "contact_title",
        "contact_email",
        "phone",
        "reason_for_interest",
    )
    @classmethod
    def trim_text_fields(cls, value: str) -> str:
        return value.strip()


class InstitutionProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="ignore")

    legal_name: str = ""
    fdic_certificate_number: str = ""
    rssd_id: str = ""
    institution_type: str = ""
    website: str = ""
    headquarters: str = ""
    admission_type: str = ""
    international_correspondent_relationships: str = ""
    has_dba: str = ""
    has_fintech_or_baas_programs: str = ""
    primary_contact_name: str = ""
    primary_contact_title: str = ""
    primary_contact_email: str = ""
    additional_responses: Dict[str, Any] = Field(default_factory=dict)


class DueDiligenceUpdate(BaseModel):
    data: Dict[str, Any]


class InstitutionProfileResponsesUpdate(BaseModel):
    responses: Dict[str, Any] = Field(default_factory=dict)


class RiskQuestionResponseUpdate(BaseModel):
    """Editable Coverbase questionnaire-response fields supplied by Hazel."""

    model_config = ConfigDict(extra="forbid")

    response: str
    selected_option_ids: Optional[List[str]] = None
    response_data: Any = None
    comment: Optional[str] = None
    reviewed: bool = True
