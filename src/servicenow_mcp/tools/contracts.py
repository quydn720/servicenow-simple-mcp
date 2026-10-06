"""Typed tool contracts and validation, independent of credentials and discovery."""

import inspect
from functools import wraps
from typing import Annotated, Literal, Union, get_type_hints

from fastmcp.exceptions import ValidationError as MCPValidationError
from fastmcp.tools.function_tool import FunctionTool, ToolResult
from servicenow_mcp.errors import ErrorEnvelope, OperationError, error_envelope
from pydantic import (
    BaseModel,
    BeforeValidator,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    create_model,
)

DIALECT = "https://json-schema.org/draft/2020-12/schema"
SysId = Annotated[
    str,
    Field(
        strict=True,
        pattern=r"^[0-9a-fA-F]{32}$",
        description="Raw 32-character hexadecimal ServiceNow sys_id; never a display name.",
    ),
]
ClearableSysId = Annotated[
    str,
    Field(
        strict=True,
        pattern=r"^(?:[0-9a-fA-F]{32})?$",
        description="Raw reference sys_id; an empty string clears the reference.",
    ),
]
Summary = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=160,
        pattern=r"\S",
        description="Required nonblank summary, up to 160 characters after trimming.",
    ),
    BeforeValidator(lambda v: v.strip() if isinstance(v, str) else v),
]
Text = Annotated[
    str,
    Field(
        strict=True,
        max_length=4000,
        description="Text up to 4000 characters after trimming; empty string clears on update.",
    ),
    BeforeValidator(lambda v: v.strip() if isinstance(v, str) else v),
]
Priority = Annotated[
    Literal["1", "2", "3", "4", "5"],
    Field(description="Raw priority choice code; 1 is highest and 5 lowest."),
]
Points = Annotated[
    int,
    Field(
        strict=True, ge=0, le=100, description="Story points, an integer from 0 to 100."
    ),
]
Limit = Annotated[
    int,
    Field(
        strict=True,
        ge=1,
        le=100,
        description="Maximum returned records, from 1 to 100; default 10. No pagination.",
    ),
]
RawQuery = Annotated[
    str | None,
    Field(
        description="Legacy argument: only omission or null is permitted. Every string is blocked with RAW_QUERY_PROHIBITED."
    ),
]
Table = Annotated[
    Literal["incident", "task", "sc_task", "problem", "change_request"],
    Field(description="Allowlisted ServiceNow table."),
]
PreviewId = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=128,
        description="Opaque single-use preview ID from the originating server/session; expires after 600 seconds.",
    ),
]
Confirmed = Annotated[
    bool,
    Field(
        strict=True,
        description="True only after explicit approval of the complete preview in a subsequent user reply; false cancels.",
    ),
]

COMMON_FIELDS = (
    "sys_id",
    "number",
    "short_description",
    "description",
    "state",
    "priority",
    "assignment_group",
    "assigned_to",
    "caller_id",
    "active",
    "sys_created_on",
    "sys_updated_on",
)
STORY_FIELDS = (
    "sys_id",
    "number",
    "short_description",
    "description",
    "acceptance_criteria",
    "story_points",
    "priority",
    "product",
    "epic",
)
EPIC_FIELDS = (
    "sys_id",
    "number",
    "short_description",
    "description",
    "product",
    "priority",
)
PRODUCT_FIELDS = ("sys_id", "name")
KNOWLEDGE_FIELDS = (
    "sys_id",
    "number",
    "short_description",
    "kb_knowledge_base",
    "workflow_state",
    "active",
    "valid_to",
    "sys_updated_on",
)
CHANGE_STATUS_FIELDS = (
    "sys_id",
    "number",
    "short_description",
    "state",
    "approval",
    "type",
    "sys_updated_on",
)
CommonFields = Annotated[
    list[Literal[*COMMON_FIELDS]],
    Field(
        min_length=1,
        max_length=len(COMMON_FIELDS),
        json_schema_extra={"uniqueItems": True},
        description="Nonempty allowlisted field selection; defaults to declared common fields. References are returned as display names.",
    ),
]
StoryFields = Annotated[
    list[Literal[*STORY_FIELDS]],
    Field(
        min_length=1,
        max_length=len(STORY_FIELDS),
        json_schema_extra={"uniqueItems": True},
        description="Nonempty allowlisted story fields; defaults to all declared story fields.",
    ),
]
EpicFields = Annotated[
    list[Literal[*EPIC_FIELDS]],
    Field(
        min_length=1,
        max_length=len(EPIC_FIELDS),
        json_schema_extra={"uniqueItems": True},
        description="Nonempty allowlisted epic fields; defaults to all declared epic fields.",
    ),
]
ProductFields = Annotated[
    list[Literal[*PRODUCT_FIELDS]],
    Field(
        min_length=1,
        max_length=len(PRODUCT_FIELDS),
        json_schema_extra={"uniqueItems": True},
        description="Nonempty allowlisted product fields; defaults to sys_id and name.",
    ),
]
FIELDS_BY_TABLE = {
    **dict.fromkeys(
        ("incident", "task", "sc_task", "problem", "change_request"), COMMON_FIELDS
    ),
    "rm_story": STORY_FIELDS,
    "rm_epic": EPIC_FIELDS,
    "cmdb_model": PRODUCT_FIELDS,
    "kb_knowledge": KNOWLEDGE_FIELDS,
}


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


def record_type(name, fields):
    # ServiceNow Table API emits raw choice/number/boolean fields as strings.
    declarations = {}
    references = {
        "assignment_group",
        "assigned_to",
        "caller_id",
        "product",
        "epic",
        "kb_knowledge_base",
    }
    for field in fields:
        if field == "sys_id":
            declarations[field] = (SysId, Field(description="Raw record identifier."))
        else:
            description = (
                "Reference display name."
                if field in references
                else "ServiceNow field value as a string."
            )
            declarations[field] = (
                str,
                Field(
                    default=None,
                    description=description + " Omitted when not returned.",
                ),
            )
    return create_model(name, __base__=ContractModel, **declarations)


CommonRecord = record_type("CommonRecord", COMMON_FIELDS)
StoryRecord = record_type("StoryRecord", STORY_FIELDS)
EpicRecord = record_type("EpicRecord", EPIC_FIELDS)
ProductRecord = record_type("ProductRecord", PRODUCT_FIELDS)
KnowledgeRecord = record_type("KnowledgeRecord", KNOWLEDGE_FIELDS)
ChangeStatusRecord = record_type("ChangeStatusRecord", CHANGE_STATUS_FIELDS)
RECORD_TYPES = {
    **dict.fromkeys(
        ("incident", "task", "sc_task", "problem", "change_request"), CommonRecord
    ),
    "rm_story": StoryRecord,
    "rm_epic": EpicRecord,
    "cmdb_model": ProductRecord,
    "kb_knowledge": KnowledgeRecord,
}


class TaskCreateFields(ContractModel):
    short_description: Summary
    description: Text = None
    priority: Priority
    assignment_group: SysId = None


class IncidentCreateFields(ContractModel):
    short_description: Summary


JournalText = Annotated[
    str,
    Field(
        strict=True,
        min_length=1,
        max_length=4000,
        pattern=r"\S",
        description="Nonblank journal entry, trimmed, up to 4000 characters; appends rather than clears history.",
    ),
    BeforeValidator(lambda v: v.strip() if isinstance(v, str) else v),
]


class IncidentJournalFields(ContractModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, json_schema_extra={"minProperties": 1}
    )
    work_notes: JournalText = None
    comments: JournalText = None


class EpicCreateFields(ContractModel):
    short_description: Summary
    description: Text = None
    product: SysId = None
    priority: Priority


class StoryCreateFields(EpicCreateFields):
    acceptance_criteria: Text = None
    story_points: Points = None
    epic: SysId = None


class EpicUpdateFields(ContractModel):
    model_config = ConfigDict(
        extra="forbid", strict=True, json_schema_extra={"minProperties": 1}
    )
    short_description: Summary = None
    description: Text = None
    product: ClearableSysId = None
    priority: Priority = None


class StoryUpdateFields(EpicUpdateFields):
    acceptance_criteria: Text = None
    story_points: Points = None
    epic: ClearableSysId = None


PAYLOAD_TYPES = {
    ("incident", "insert"): IncidentCreateFields,
    ("incident", "update"): IncidentJournalFields,
    ("task", "insert"): TaskCreateFields,
    ("rm_story", "insert"): StoryCreateFields,
    ("rm_epic", "insert"): EpicCreateFields,
    ("rm_story", "update"): StoryUpdateFields,
    ("rm_epic", "update"): EpicUpdateFields,
}
PREVIEW_TYPES = {}
for (table, operation), payload_type in PAYLOAD_TYPES.items():
    attrs = {
        "operation": (Literal[operation], Field(description="Proposed operation.")),
        "table": (Literal[table], Field(description="Target ServiceNow table.")),
        "fields": (
            payload_type,
            Field(description="Exact normalized payload saved for review."),
        ),
    }
    if operation == "update":
        attrs["sys_id"] = (SysId, Field(description="Raw target record ID."))
    PREVIEW_TYPES[table, operation] = create_model(
        f"{payload_type.__name__}Preview", __base__=ContractModel, **attrs
    )

# Union schemas are self-contained through Pydantic's local $defs.
AnyPreview = Union[tuple(PREVIEW_TYPES.values())]
WriteError = create_model(
    "WriteError",
    __base__=ErrorEnvelope,
    retry_guidance=(
        str,
        Field(
            default=None,
            description="Reconciliation or fresh-preview recovery guidance.",
        ),
    ),
    preview=(
        AnyPreview,
        Field(default=None, description="Exact saved preview when available."),
    ),
)


def result_type(name, record, table, collection=False):
    attrs = {"table": (table, Field(description="Source ServiceNow table."))}
    if collection:
        attrs["count"] = (
            Annotated[int, Field(ge=0, le=100)],
            Field(description="Number of returned records; equals records length."),
        )
        attrs["records"] = (
            Annotated[list[record], Field(max_length=100)],
            Field(description="Bounded returned records; no pagination."),
        )
    else:
        attrs["sys_id"] = (SysId, Field(description="Requested raw record identifier."))
        attrs["record"] = (
            record,
            Field(
                description="Declared record fields; its sys_id matches the requested ID."
            ),
        )
    return create_model(name, __base__=ContractModel, **attrs)


READ_RESULTS = {}
for entity, record, table in (
    ("common", CommonRecord, Table),
    ("story", StoryRecord, Literal["rm_story"]),
    ("epic", EpicRecord, Literal["rm_epic"]),
    ("product", ProductRecord, Literal["cmdb_model"]),
    ("incident", CommonRecord, Literal["incident"]),
    ("knowledge", KnowledgeRecord, Literal["kb_knowledge"]),
    ("change_status", ChangeStatusRecord, Literal["change_request"]),
):
    READ_RESULTS[entity, "get"] = result_type(
        f"{entity.title()}GetResult", record, table
    )
    READ_RESULTS[entity, "list"] = result_type(
        f"{entity.title()}ListResult", record, table, collection=True
    )

PREPARE_RESULTS = {}
for key, preview in PREVIEW_TYPES.items():
    pending = create_model(
        f"{preview.__name__}Result",
        __base__=ContractModel,
        status=(
            Literal["awaiting_confirmation"],
            Field(description="No ServiceNow request was made."),
        ),
        preview_id=(
            PreviewId,
            Field(description="Opaque single-use server/session-bound ID."),
        ),
        preview=(preview, Field(description="Complete saved operation to review.")),
        expires_in_seconds=(
            Literal[600],
            Field(description="Lifetime in seconds at preview creation."),
        ),
        message=(
            str,
            Field(description="Explicit review and confirmation instructions."),
        ),
    )
    PREPARE_RESULTS[key] = pending | WriteError

Cancelled = create_model(
    "Cancelled",
    __base__=ContractModel,
    status=(Literal["cancelled"], Field(description="No write was made.")),
    preview=(AnyPreview, Field(description="Discarded saved operation.")),
    message=(str, Field(description="Cancellation message.")),
)
WriteSuccesses = []
for table in ("incident", "task", "rm_story", "rm_epic"):
    WriteSuccesses.append(
        create_model(
            f"{table}WriteSuccess",
            __base__=ContractModel,
            table=(Literal[table], Field(description="Written table.")),
            record=(
                RECORD_TYPES[table],
                Field(description="Saved record, projected to declared fields."),
            ),
        )
    )
CONFIRM_RESULT = Union[tuple(WriteSuccesses)] | Cancelled | WriteError


def select_fields(fields, allowed):
    selected = list(allowed) if fields is None else list(fields)
    if (
        not selected
        or len(selected) != len(set(selected))
        or any(f not in allowed for f in selected)
    ):
        raise ValueError(
            "fields must be a nonempty, unique selection of declared fields."
        )
    # An identifier is always returned so rows remain identifiable.
    return list(dict.fromkeys(["sys_id", *selected]))


def project_record(record, table, fields=None, *, failure_outcome="failed"):
    if not isinstance(record, dict):
        raise OperationError("UPSTREAM_ERROR", outcome=failure_outcome)
    selected = select_fields(fields, FIELDS_BY_TABLE[table])
    projected = {key: value for key, value in record.items() if key in selected}
    try:
        RECORD_TYPES[table].model_validate(projected)
    except ValidationError:
        raise OperationError("UPSTREAM_ERROR", outcome=failure_outcome) from None
    return projected


def project_records(records, table, fields, limit):
    if not isinstance(records, list) or len(records) > limit:
        raise OperationError("UPSTREAM_ERROR", outcome="failed")
    return [project_record(record, table, fields) for record in records]


def normalize_payload(table, operation, payload):
    normalized = {
        key: value.strip()
        if isinstance(value, str)
        and key
        in {
            "short_description",
            "description",
            "acceptance_criteria",
            "work_notes",
            "comments",
        }
        else value
        for key, value in payload.items()
    }
    if operation == "update" and not normalized:
        raise ValueError("At least one field must be supplied for update.")
    return (
        PAYLOAD_TYPES[table, operation]
        .model_validate(normalized)
        .model_dump(exclude_unset=True)
    )


class ContractFunctionTool(FunctionTool):
    async def run(self, arguments):
        try:
            return await super().run(arguments)
        except (MCPValidationError, ValidationError, TypeError):
            data = error_envelope(
                ValueError(), confirmation=self.name == "confirm_pending_write"
            )
            return ToolResult(structured_content=data, is_error=True)

    def convert_result(self, value):
        if isinstance(value, dict) and value.get("status") == "error":
            return ToolResult(structured_content=value, is_error=True)
        return super().convert_result(value)


def contract_tool(mcp, output, *, input_schema_extra=None, **metadata):
    """Publish schemas and validate direct and MCP invocations and results."""
    adapter = TypeAdapter(output | WriteError)
    schema = {"$schema": DIALECT, "type": "object", **adapter.json_schema()}

    def clean_defaults(node):
        if isinstance(node, dict):
            # Omission-only fields use internal None defaults; do not advertise
            # a null default for a schema that rejects explicit null values.
            if (
                node.get("default", ...) is None
                and node.get("type") != "null"
                and not any(
                    part.get("type") == "null" for part in node.get("anyOf", [])
                )
            ):
                del node["default"]
            for value in node.values():
                clean_defaults(value)
        elif isinstance(node, list):
            for value in node:
                clean_defaults(value)

    clean_defaults(schema)

    def decorate(fn):
        signature = inspect.signature(fn)
        hints = get_type_hints(fn, include_extras=True)

        def arguments(args, kwargs):
            try:
                bound = signature.bind(*args, **kwargs)
            except TypeError:
                raise OperationError("VALIDATION_ERROR") from None
            bound.apply_defaults()
            for name, value in bound.arguments.items():
                if name == "ctx":
                    continue
                # Normalize textual inputs before applying schema length bounds.
                if name in {
                    "short_description",
                    "description",
                    "acceptance_criteria",
                } and isinstance(value, str):
                    value = value.strip()
                bound.arguments[name] = TypeAdapter(hints[name]).validate_python(
                    value, strict=True
                )
            return bound

        confirmation = fn.__name__ == "confirm_pending_write"

        def result(value):
            try:
                return adapter.validate_python(value).model_dump(exclude_unset=True)
            except ValidationError:
                raise OperationError(
                    "INTERNAL_ERROR",
                    outcome="unknown" if confirmation else "not_attempted",
                ) from None

        if inspect.iscoroutinefunction(fn):

            @wraps(fn)
            async def wrapped(*args, **kwargs):
                try:
                    bound = arguments(args, kwargs)
                    return result(await fn(*bound.args, **bound.kwargs))
                except Exception as error:
                    return result(error_envelope(error, confirmation=confirmation))
        else:

            @wraps(fn)
            def wrapped(*args, **kwargs):
                try:
                    bound = arguments(args, kwargs)
                    return result(fn(*bound.args, **bound.kwargs))
                except Exception as error:
                    return result(error_envelope(error))

        tool = ContractFunctionTool.from_function(
            wrapped, output_schema=schema, **metadata
        )
        tool.parameters["$schema"] = DIALECT
        for name, prop in tool.parameters["properties"].items():
            if "description" not in prop:
                description = next(
                    (
                        part["description"]
                        for part in prop.get("anyOf", [])
                        if "description" in part
                    ),
                    name.replace("_", " "),
                )
                prop["description"] = (
                    f"Optional; null leaves this value unspecified. {description}"
                )
        if input_schema_extra:
            tool.parameters.update(input_schema_extra)
        mcp.add_tool(tool)
        return wrapped

    return decorate
