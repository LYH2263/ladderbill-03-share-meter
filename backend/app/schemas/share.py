"""合表分摊模块的请求结构（输出沿用项目惯例返回裸 dict）。"""
import re

from pydantic import BaseModel, Field, field_validator

PERIOD_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


class ShareMemberIn(BaseModel):
    account_id: int
    ratio: int = Field(ge=1, le=100, description="整数百分比 1~100")


class ShareSchemeIn(BaseModel):
    name: str = Field(min_length=1, max_length=50)
    master_account_id: int
    remainder_account_id: int
    members: list[ShareMemberIn] = Field(min_length=2)

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("方案名称不能为空")
        return v


class ShareAllocateIn(BaseModel):
    scheme_id: int
    period: str = Field(description="账期，格式 YYYY-MM")
    master_kwh: float = Field(ge=0)
    force: bool = False

    @field_validator("period")
    @classmethod
    def _check_period(cls, v: str) -> str:
        if not PERIOD_RE.match(v):
            raise ValueError("账期格式必须为 YYYY-MM，例如 2026-09")
        return v
