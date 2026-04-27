import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

ReasoningEffort = Literal["low", "medium", "high"]


class EvalSuiteCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    system_prompt: str = ""
    scoring_method: str = "exact_match"


class EvalSuiteUpdate(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None
    system_prompt: str | None = None
    scoring_method: str | None = None


class EvalSuiteResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    system_prompt: str
    scoring_method: str
    created_at: datetime
    updated_at: datetime
    test_cases: list["EvalTestCaseResponse"] = []

    class Config:
        from_attributes = True


class EvalSuiteListResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime

    class Config:
        from_attributes = True


class EvalTestCaseCreate(BaseModel):
    input: str = ""
    expected_output: str = ""
    input_mode: str = "text"
    expected_mode: str = "text"
    order_index: int = 0


class EvalTestCaseUpdate(BaseModel):
    input: str | None = None
    expected_output: str | None = None
    input_mode: str | None = None
    expected_mode: str | None = None
    order_index: int | None = None


class EvalTestCaseResponse(BaseModel):
    id: uuid.UUID
    suite_id: uuid.UUID
    input: str
    expected_output: str
    input_mode: str
    expected_mode: str
    order_index: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class RunEvalsRequest(BaseModel):
    credential_id: uuid.UUID
    models: list[str] = Field(min_length=1)
    scoring_method: str = "exact_match"
    temperature: float = Field(ge=0.0, le=2.0, default=0.7)
    reasoning_effort: ReasoningEffort | None = None
    runs_per_test: int = Field(ge=1, le=20, default=1)
    max_tokens: int | None = None
    judge_credential_id: uuid.UUID | None = None
    judge_model: str | None = None


class EvalRunResultResponse(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    test_case_id: uuid.UUID | None
    model_id: str
    input_snapshot: str
    expected_output_snapshot: str
    actual_output: str
    score: str
    explanation: str | None = None
    latency_ms: int | None
    tokens_used: int | None
    error: str | None
    created_at: datetime
    run_order: int | None = None

    class Config:
        from_attributes = True


class EvalRunResponse(BaseModel):
    id: uuid.UUID
    suite_id: uuid.UUID
    name: str
    system_prompt_snapshot: str
    models: list[str]
    scoring_method: str
    temperature: float
    reasoning_effort: str | None = None
    max_tokens: int | None
    status: str
    created_at: datetime
    completed_at: datetime | None
    results: list[EvalRunResultResponse] = []

    class Config:
        from_attributes = True


class EvalRunListResponse(BaseModel):
    id: uuid.UUID
    name: str
    models: list[str]
    status: str
    scoring_method: str = "exact_match"
    created_at: datetime
    completed_at: datetime | None
    pass_count: int = 0
    total_count: int = 0

    class Config:
        from_attributes = True


class EvalRunRenameRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class OptimizePromptRequest(BaseModel):
    credential_id: uuid.UUID
    model: str = "gpt-4o"
    system_prompt: str = ""


class OptimizePromptResponse(BaseModel):
    optimized_prompt: str


class GenerateTestDataRequest(BaseModel):
    credential_id: uuid.UUID
    model: str = "gpt-4o"
    count: int = Field(ge=1, le=20, default=5)


class GenerateTestDataResponse(BaseModel):
    test_cases: list[EvalTestCaseCreate]


EvalSuiteResponse.model_rebuild()
