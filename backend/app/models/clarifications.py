"""Hazel-owned review clarification persistence helpers.

Coverbase has not confirmed a supported first-class clarification resource.
These records are therefore intentionally local and must not be synchronized
through Coverbase's dashboard-only email, comment, activity, or audit APIs.
"""

from __future__ import annotations

from typing import Any

from app.db import row_dict


ACTION_REQUIRED_STATUSES = {"open", "draft"}
UNRESOLVED_STATUSES = ACTION_REQUIRED_STATUSES | {"submitted"}
TERMINAL_COVERBASE_STATUSES = {"accepted", "rejected", "partial"}


def clarification_payload(row, uploaded_document=None) -> dict[str, Any] | None:
    clarification = row_dict(row)
    if not clarification:
        return None
    clarification["document_required"] = bool(clarification["document_required"])
    clarification["uploaded_document"] = row_dict(uploaded_document)
    return clarification


def review_state_for(
    coverbase_status: str | None, current_clarification: dict[str, Any] | None
) -> str:
    """Apply the member-facing review-state priority approved for Hazel."""
    if coverbase_status == "accepted":
        return "approved"
    if coverbase_status == "rejected":
        return "rejected"
    if coverbase_status == "partial":
        return "partial"
    if current_clarification:
        if current_clarification["status"] in ACTION_REQUIRED_STATUSES:
            return "action_required"
        if current_clarification["status"] == "submitted":
            return "response_submitted"
    return "under_review"
