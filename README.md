# 12-ladderbill（阶梯电费）

Ladderbill — 居民阶梯电价分段累进（含尖峰系数）

## 启动

```bash
docker compose up --build
```

| 入口 | 地址 |
| --- | --- |
| 前端 | http://localhost:4100 |
| API | http://localhost:9100 |

## 主链

抄表录入 → 阶梯分段计费 → 账单明细

## 模块

- 合表分摊（/share）：维护分摊方案（主表来源户、成员整数百分比、余数归属成员），按账期把主表电量拆到成员抄表；同账期重算需 force，旧分摊抄表软标记可溯源，分摊之和与主表电量对账平衡。

## 技术栈

Python 3.12 + FastAPI + SQLite；Vue 3 + Vite + Nginx。
