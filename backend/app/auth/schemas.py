from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: Annotated[str, Field(strict=True, min_length=1, max_length=100)]
    password: Annotated[str, Field(strict=True, min_length=1, max_length=128)]
