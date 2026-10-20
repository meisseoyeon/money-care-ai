from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class TransferCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    counterparty_id: Annotated[str, Field(min_length=1, max_length=100)]
    amount: Annotated[StrictInt, Field(gt=0, le=1_000_000_000)]
