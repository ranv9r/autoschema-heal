"""
Canonical Target Schema representation and validation engine.
Supports Pydantic v2 models and raw JSON Schema definitions.
"""

from __future__ import annotations
import json
from typing import Any, Dict, List, Optional, Tuple, Type
from pydantic import BaseModel, ValidationError
import jsonschema


class TargetSchema:
    """
    Encapsulates a Canonical Target Schema with fast validation and schema introspection.
    """

    def __init__(self, pydantic_model: Optional[Type[BaseModel]] = None, json_schema: Optional[Dict[str, Any]] = None) -> None:
        if pydantic_model is None and json_schema is None:
            raise ValueError("Either pydantic_model or json_schema must be supplied.")
        
        self.pydantic_model = pydantic_model
        if pydantic_model is not None:
            self.json_schema = pydantic_model.model_json_schema()
        else:
            self.json_schema = json_schema  # type: ignore

        # Pre-compile JSON Schema validator
        self._validator = jsonschema.Draft202012Validator(self.json_schema)

    def validate(self, data: Any) -> Tuple[bool, Optional[str]]:
        """
        Validates output data against canonical schema.
        Returns (is_valid, error_message).
        """
        if self.pydantic_model is not None:
            try:
                self.pydantic_model.model_validate(data)
                return True, None
            except ValidationError as e:
                return False, str(e)
            except Exception as e:
                return False, f"Unexpected validation exception: {str(e)}"
        else:
            errors = list(self._validator.iter_errors(data))
            if not errors:
                return True, None
            first_err = errors[0]
            path = ".".join(str(p) for p in first_err.absolute_path) or "root"
            return False, f"At {path}: {first_err.message}"

    def get_json_schema_str(self) -> str:
        """Returns pretty JSON schema string for synthesis prompts."""
        return json.dumps(self.json_schema, indent=2)

    def get_field_summary(self) -> Dict[str, Any]:
        """
        Extracts top-level and nested required fields and types for synthesis assistance.
        """
        props = self.json_schema.get("properties", {})
        required = set(self.json_schema.get("required", []))
        summary = {}
        for prop_name, prop_meta in props.items():
            summary[prop_name] = {
                "type": prop_meta.get("type", "any"),
                "required": prop_name in required,
                "description": prop_meta.get("description", ""),
                "default": prop_meta.get("default", None),
            }
        return summary
