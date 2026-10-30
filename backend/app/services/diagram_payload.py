"""Validated data contracts for Gantt and entity relationship widgets."""

from datetime import date, datetime, timezone
from typing import Any, Literal, Self

from fastapi import HTTPException
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator


class GanttTask(BaseModel):
    """A scheduled task with an optional completion percentage and predecessor ids."""

    id: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=255)
    start: str
    end: str
    progress: float = Field(default=0, ge=0, le=100, allow_inf_nan=False)
    dependencies: list[str] = Field(default_factory=list, max_length=500)

    @field_validator("start", "end")
    @classmethod
    def normalize_date(cls, value: str) -> str:
        """Interpret date-only and timezone-free ISO values as UTC."""
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        parsed = parsed.astimezone(timezone.utc)
        if not date(1900, 1, 1) <= parsed.date() <= date(2200, 12, 31):
            raise ValueError("Task dates must be between 1900 and 2200")
        return parsed.isoformat()

    @model_validator(mode="after")
    def validate_range(self) -> Self:
        """Reject reversed ranges."""
        if self.end < self.start:
            raise ValueError("Task end must be on or after start")
        return self


class GanttData(BaseModel):
    tasks: list[GanttTask] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        """Require unique ids and existing, non-self predecessors."""
        ids = {task.id for task in self.tasks}
        if len(ids) != len(self.tasks):
            raise ValueError("Task ids must be unique")
        for task in self.tasks:
            if any(dep not in ids or dep == task.id for dep in task.dependencies):
                raise ValueError("Task dependencies must reference another task id")
        return self


class EntityField(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    type: str = Field(default="", max_length=255)
    key: Literal["PK", "FK", "PK/FK", ""] = ""


class Entity(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    label: str = Field(min_length=1, max_length=255)
    fields: list[EntityField] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_fields(self) -> Self:
        """Field names identify relationship endpoints within an entity."""
        if len({field.name for field in self.fields}) != len(self.fields):
            raise ValueError("Field names within an entity must be unique")
        return self


class EntityRelation(BaseModel):
    source: str = Field(min_length=1, max_length=255)
    target: str = Field(min_length=1, max_length=255)
    source_field: str | None = Field(default=None, max_length=255, alias="sourceField")
    target_field: str | None = Field(default=None, max_length=255, alias="targetField")
    label: str = Field(default="", max_length=255)
    cardinality: Literal["one-to-one", "one-to-many", "many-to-one", "many-to-many"] = "one-to-many"


class EntityDiagramData(BaseModel):
    entities: list[Entity] = Field(default_factory=list, max_length=100)
    relations: list[EntityRelation] = Field(default_factory=list, max_length=500)

    @model_validator(mode="after")
    def validate_references(self) -> Self:
        """Require unique entity ids and valid entity and field endpoints."""
        entities = {entity.id: entity for entity in self.entities}
        if len(entities) != len(self.entities):
            raise ValueError("Entity ids must be unique")
        for relation in self.relations:
            for entity_id, field in (
                (relation.source, relation.source_field),
                (relation.target, relation.target_field),
            ):
                entity = entities.get(entity_id)
                if entity is None or (
                    field is not None and field not in {f.name for f in entity.fields}
                ):
                    raise ValueError("Relationships must reference existing entities and fields")
        return self


def build_diagram_data(chart_type: str, data: Any) -> dict[str, Any]:
    """Validate structured widget data, with actionable errors for workflow test runs."""
    try:
        model = GanttData if chart_type == "gantt" else EntityDiagramData
        return model.model_validate(data).model_dump(by_alias=True)
    except ValidationError as exc:
        errors = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors(include_input=False, include_url=False)
        )
        raise HTTPException(status_code=400, detail=f"Invalid {chart_type} data: {errors}") from exc
