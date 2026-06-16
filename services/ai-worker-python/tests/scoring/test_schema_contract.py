"""Contract + Gemini-strict-safety tests for PER_CLIP_VIRALITY_SCHEMA (P2-S3).

The schema is sent to Gemini via OpenRouter with ``response_format: json_schema
strict:true``. Gemini supports only a subset of JSON Schema, so these tests pin
the shape and forbid keywords that trigger 400 InvalidArgument or silent
free-text degradation.
"""

from fliphouse_worker.scoring import PER_CLIP_VIRALITY_SCHEMA, SCHEMA_NAME

# Independent re-declaration (drift guard, same pattern as the doc04 contract test).
EXPECTED_PROPERTY_ORDER = [
    "rationale",
    "hook",
    "emotion",
    "payoff",
    "visual",
    "audio",
    "pacing",
    "confidence",
    "modalities_used",
]

GEMINI_UNSAFE_KEYWORDS = {
    "oneOf",
    "allOf",
    "anyOf",
    "$ref",
    "$defs",
    "patternProperties",
    "prefixItems",
    "format",
    "minimum",
    "maximum",
    "minItems",
    "maxItems",
    "enum",
    "propertyOrdering",
}


def test_schema_name_is_pinned():
    assert SCHEMA_NAME == "per_clip_virality"


def test_schema_all_properties_in_required():
    schema = PER_CLIP_VIRALITY_SCHEMA
    assert set(schema["required"]) == set(schema["properties"])
    assert len(schema["required"]) == 9


def test_schema_additional_properties_is_false():
    # exactly the bool False (strict mode), not 0/None.
    assert PER_CLIP_VIRALITY_SCHEMA["additionalProperties"] is False


def test_schema_property_order_is_emission_order():
    assert list(PER_CLIP_VIRALITY_SCHEMA["properties"].keys()) == EXPECTED_PROPERTY_ORDER


def test_schema_score_fields_are_plain_integer():
    props = PER_CLIP_VIRALITY_SCHEMA["properties"]
    for field in ("hook", "emotion", "payoff", "visual", "audio", "pacing", "confidence"):
        assert props[field]["type"] == "integer", field
    assert props["modalities_used"]["type"] == "array"
    assert props["modalities_used"]["items"] == {"type": "string"}
    assert props["rationale"]["type"] == "string"


def test_schema_uses_only_gemini_safe_keywords():
    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                assert key not in GEMINI_UNSAFE_KEYWORDS, f"unsafe keyword: {key}"
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(PER_CLIP_VIRALITY_SCHEMA)


def test_visual_audio_descriptions_define_minus_one_sentinel():
    props = PER_CLIP_VIRALITY_SCHEMA["properties"]
    for field in ("visual", "audio"):
        desc = props[field]["description"]
        assert "-1" in desc, field
        assert "not assessed" in desc.lower(), field
        # must NOT lead with a bare "0-100" framing (the must_fix contradiction).
        assert not desc.lstrip().startswith("0-100"), field
