"""合表电量分摊模块。

能力：
- 分摊方案落库：主表电量来源户、成员户列表、整数百分比例（和恰为 100）、余数归属成员；
- 按账期执行分摊：主表电量拆到各成员抄表，除不尽电量落到归属成员；
- 同账期重复分摊需 force，重算对旧抄表做 superseded 软标记而非物理删除；
- 成员抄表带分摊来源标记，并提供对账核验（主表电量 = 成员分摊之和 + 余数规则）。
"""
from app.modules.share_meter.engine import ShareValidationError, allocate, validate_ratios

__all__ = ["ShareValidationError", "allocate", "validate_ratios"]
