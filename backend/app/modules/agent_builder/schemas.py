"""What people send, and the only shape of model output that is accepted."""

from typing import Annotated, Any, Self

from pydantic import AfterValidator, BaseModel, BeforeValidator, ConfigDict, model_validator
from pydantic_core import PydanticCustomError

from app.core.text import Name, check_text, is_blank
from app.modules.agent_builder.hidden_text import has_hidden_text
from app.modules.agents.schemas import DESCRIPTION_MAX, PURPOSE_MAX, Instructions
from app.modules.providers.selection import Disclosure

ANSWER_MAX, ANSWERS_TOTAL_MAX = 1_000, 3_000


def _optional_answer(value: str) -> str:
    return check_text(value.strip(), ANSWER_MAX)


def _required_answer(value: str) -> str:
    value = _optional_answer(value)
    if is_blank(value):
        raise PydanticCustomError("answer_blank", "Please answer this question.")
    return value


RequiredAnswer = Annotated[str, AfterValidator(_required_answer)]
OptionalAnswer = Annotated[str, AfterValidator(_optional_answer)]


class Answers(BaseModel):
    model_config = ConfigDict(extra="forbid")

    purpose: RequiredAnswer
    tasks: RequiredAnswer
    tone: OptionalAnswer = ""
    constraints: OptionalAnswer = ""
    extra: OptionalAnswer = ""

    @model_validator(mode="after")
    def _limit_total(self) -> Self:
        if sum(len(answer) for answer in self.model_dump().values()) > ANSWERS_TOTAL_MAX:
            raise PydanticCustomError(
                "answers_too_long",
                "All answers together must be at most {maximum} characters.",
                {"maximum": ANSWERS_TOTAL_MAX},
            )
        return self


def _visible(value: Any) -> Any:
    if isinstance(value, str) and has_hidden_text(value):
        raise PydanticCustomError("hidden_text", "Contains hidden characters.")
    return value


def _short_text(maximum: int) -> AfterValidator:
    return AfterValidator(lambda value: check_text(value.strip(), maximum))


Visible = BeforeValidator(_visible)  # sees what the other validators would strip


class AgentDraft(BaseModel):
    """Every field is required and nothing else is allowed.

    Not derived from AgentCreate: whatever that accepts later must not become open to a model.
    """

    model_config = ConfigDict(extra="forbid", strict=True)

    name: Annotated[Name, Visible]
    purpose: Annotated[str, _short_text(PURPOSE_MAX), Visible]
    description: Annotated[str, _short_text(DESCRIPTION_MAX), Visible]
    instructions: Annotated[Instructions, Visible]


class BuilderStatus(BaseModel):
    available: bool
    disclosure: Disclosure


class DraftOut(BaseModel):
    draft: AgentDraft
    sample: bool  # made by the mock, not by an AI
