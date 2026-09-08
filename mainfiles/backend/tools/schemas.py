"""Tool schema definitions and validation."""
from __future__ import annotations

from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field


class ToolDefinition(BaseModel):
    """Complete definition of a tool available to the model."""
    model_config = ConfigDict(extra="forbid")

    name: str
    description: str
    parameters: dict[str, Any]
    handler: Callable[..., Any] | None = Field(default=None, exclude=True)
    capabilities: list[str] = Field(default_factory=list)
    # Phase 7: Capability metadata (optional, defaults to safe values)
    safety_level: str = "safe"  # "safe", "caution", "destructive"
    read_only: bool = True
    category: str = "general"  # "web", "file", "code", "general"
    requires_confirmation: bool = False


class ToolCall(BaseModel):
    """Canonical tool call from the model."""
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    arguments: dict[str, Any]


class ToolResult(BaseModel):
    """Canonical tool result returned to the model."""
    model_config = ConfigDict(extra="forbid")

    tool_call_id: str
    name: str
    content: str
    data: dict[str, Any] | None = None
    error: str | None = None
    is_error: bool = False

    def __init__(self, **data):
        # Ensure content is always a string (never None)
        if "content" in data and data["content"] is None:
            data["content"] = ""
        super().__init__(**data)

    @property
    def success(self) -> bool:
        """Return True if the tool execution was successful."""
        return not self.is_error

    def model_dump_for_llm(self) -> dict[str, Any]:
        """Return a dict suitable for sending to the LLM as a tool result message."""
        return {
            "role": "tool",
            "tool_call_id": self.tool_call_id,
            "content": self.content,
        }


def validate_tool_arguments(definition: ToolDefinition, arguments: dict[str, Any]) -> tuple[bool, str | None]:
    try:
        _validate_json_schema(arguments, definition.parameters)
        return True, None
    except Exception as e:
        return False, str(e)


def _validate_json_schema(instance: dict[str, Any], schema: dict[str, Any]) -> None:
    schema_type = schema.get("type")
    if schema_type == "object":
        if not isinstance(instance, dict):
            raise ValueError(f"Expected object, got {type(instance).__name__}")
        required = schema.get("required", [])
        properties = schema.get("properties", {})
        additional_properties = schema.get("additionalProperties", True)
        for req in required:
            if req not in instance:
                raise ValueError(f"Missing required property: {req}")
        for key, value in instance.items():
            if key in properties:
                _validate_json_schema(value, properties[key])
            elif not additional_properties:
                if additional_properties is False:
                    raise ValueError(f"Additional property not allowed: {key}")
                elif isinstance(additional_properties, dict):
                    _validate_json_schema(value, additional_properties)
    elif schema_type == "string":
        if not isinstance(instance, str):
            raise ValueError(f"Expected string, got {type(instance).__name__}")
        if "enum" in schema and instance not in schema["enum"]:
            raise ValueError(f"Value '{instance}' not in enum: {schema['enum']}")
    elif schema_type == "number":
        if not isinstance(instance, (int, float)):
            raise ValueError(f"Expected number, got {type(instance).__name__}")
    elif schema_type == "integer":
        if not isinstance(instance, int):
            raise ValueError(f"Expected integer, got {type(instance).__name__}")
    elif schema_type == "boolean":
        if not isinstance(instance, bool):
            raise ValueError(f"Expected boolean, got {type(instance).__name__}")
    elif schema_type == "array":
        if not isinstance(instance, list):
            raise ValueError(f"Expected array, got {type(instance).__name__}")
        items_schema = schema.get("items")
        if items_schema:
            for item in instance:
                _validate_json_schema(item, items_schema)
    elif schema_type is None:
        pass
    else:
        pass


def tool_definition_to_openai_function(definition: ToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": definition.name,
            "description": definition.description,
            "parameters": definition.parameters,
        },
    }


def tool_definition_to_anthropic_tool(definition: ToolDefinition) -> dict[str, Any]:
    return {
        "name": definition.name,
        "description": definition.description,
        "input_schema": definition.parameters,
    }
