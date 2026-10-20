from pydantic import BaseModel, ConfigDict, StrictBool, field_validator


class DemoSessionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    acknowledged: StrictBool
    monitoring_consented: StrictBool
    restart: StrictBool = False

    @field_validator("acknowledged")
    @classmethod
    def require_acknowledgement(cls, value):
        if not value:
            raise ValueError("합성 데이터 체험 안내를 확인해 주세요.")
        return value


class MonitoringConsent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consented: StrictBool
