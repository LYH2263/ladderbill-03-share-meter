"""合表电量分摊模块：方案管理 + 按账期执行 + 余数归属 + 软标记重算 + 对账。"""

from app.modules.share_meter.router import router
from app.modules.share_meter.schema import ensure_schema
from app.modules.share_meter.service import ShareError, ShareService

__all__ = ["router", "ensure_schema", "ShareError", "ShareService"]
