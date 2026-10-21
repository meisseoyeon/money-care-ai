from pydantic import BaseModel, ConfigDict, StrictBool


class MonitoringConsent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consented: StrictBool
