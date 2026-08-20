"""Hazel-owned fallback schema for the consolidated Due Diligence step."""

HAZEL_INSTITUTION_PROFILE_SCHEMA = {
    "schema_version": "2026-08-04",
    "title": "Due Diligence",
    "description": "Provide additional details about your institution and intended use of the Hazel Network.",
    "sections": [
        {
            "id": "relationship-details",
            "title": "Relationship Details",
            "kind": "questions",
            "questions": [
                {
                    "id": "pilot",
                    "storage_key": "admission_type",
                    "label": "Is this institution currently a pilot member of the Hazel Network, or is this a standard admission?",
                    "options": ["Pilot member", "Standard admission", "Unsure"],
                },
                {
                    "id": "correspondent",
                    "storage_key": "international_correspondent_relationships",
                    "label": "Does this institution maintain any correspondent banking relationships with banks outside the United States?",
                    "options": ["Yes", "No", "Unsure"],
                },
                {
                    "id": "dba",
                    "storage_key": "has_dba",
                    "label": "Does this institution plan to offer network products or services under any trade names or DBAs different from its legal entity name?",
                    "options": ["Yes", "No", "Unsure"],
                },
                {
                    "id": "thirdParty",
                    "storage_key": "has_fintech_or_baas_programs",
                    "label": "Will this institution use the Hazel Network to support any fintech partnerships, banking-as-a-service programs, or other third-party programs?",
                    "options": ["Yes", "No", "Unsure"],
                },
                {
                    "id": "foreignOwnership",
                    "label": "Does this institution have any parent company or owners (direct or indirect) that are foreign persons or entities?",
                    "options": ["Yes", "No", "Unsure"],
                },
                {
                    "id": "integration",
                    "label": "Which integration model best fits this institution's intended use of the Hazel Network?",
                    "options": [
                        "Basic (standard settlement and reporting)",
                        "Advanced (custom integrations)",
                        "Enterprise (deep system integration)",
                    ],
                },
                {
                    "id": "activity",
                    "label": "Will this institution's network activity be limited to the United States, or will it include international counterparties?",
                    "options": ["Domestic only", "International activity expected", "Unsure at this time"],
                },
            ],
            "supporting_information": {
                "label": "Custom response",
                "placeholder": "Or write a custom answer",
            },
        },
    ],
}


def is_valid_institution_profile_schema(schema: object) -> bool:
    if not isinstance(schema, dict) or not isinstance(schema.get("sections"), list):
        return False
    return any(
        isinstance(section, dict)
        and section.get("kind") == "questions"
        and isinstance(section.get("questions"), list)
        for section in schema["sections"]
    )
