# 深度登记 果胶批配试算台

- 规模：中型
- 核心规则：离散称量同时验湿重、干重与凝胶区间，先最少批再裁决到期先后；合桶回用只看整桶复验，但任何一份原批到期仍卡住整桶。

## 功能模块

| 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
|---|---|---|---|---|
| M1 批次化验采信 | 扫描原件与冲突 | POST /api/assay | `app/modules/assay/service.py` | `tests/test_assay.py` |
| M2 干物折算 | 检查过期与干物库存 | POST /api/dry | `app/modules/dry/service.py` | `tests/test_dry.py` |
| M3 合桶回用判定 | 整桶复验续领与卡桶 | POST /api/reuse | `app/modules/reuse/service.py` | `tests/test_reuse.py` `tests/test_reuse_oracle.py` |
| M4 目标区间验方 | 输入提案并查约束 | POST /api/formula | `app/modules/formula/service.py` | `tests/test_formula.py` `tests/test_plan_contract.py` |
| M5 整数配料寻优 | 按称量刻度求组合 | POST /api/blend | `app/modules/blend/search.py` | `tests/test_blend.py` `tests/test_solver_oracle.py` |
| M6 领用与余量核算 | 核对库存、领用和缺口 | POST /api/stock | `app/modules/stock/balance.py` | `tests/test_stock.py` |
| M7 回用领用账本 | 并发领料、重试与对账 | POST /api/issues | `app/modules/ledger/service.py` | `tests/test_issue.py` |
| M8 批次留档复跑 | 留档并验证重复提交 | POST /api/batches | `app/modules/batches/storage.py` | `tests/test_batches.py` |
| M9 试配证据签发 | 复核试配状态并下载 | GET /api/certificate/<id> | `app/modules/certificate/service.py` | `tests/test_certificate.py` |

## 陷阱登记

| TRAP | 原件现象 | 朴素错误 | 处理 | 位置 | 测试 |
|---|---|---|---|---|---|
| TRAP-02 | 化验首列有 BOM | 批号列未识别 | 移除首 BOM | `app/modules/assay/reader.py` | `tests/test_assay.py::test_bom_and_split_header` |
| TRAP-04 | 化验接表 | 表头进清单 | 统计分段 | `app/modules/assay/reader.py` | `tests/test_assay.py::test_bom_and_split_header` |
| TRAP-05 | PJ-10 附多列 | 误读化验结果 | 逐行隔离 | `app/modules/assay/reader.py` | `tests/test_assay.py::test_extra_column_keeps_line` |
| TRAP-06 | PJ-01 全角千分位 | 原料重量读错 | NFKC 与格式校验 | `app/modules/assay/units.py` | `tests/test_assay.py::test_fullwidth_thousands_and_decimal_contract` |
| TRAP-07 | 哨兵和空格 | 当成零水分 | 稳定原因区分 | `app/reasons.py` | `tests/test_assay.py::test_blank_and_sentinel_are_distinct` |
| TRAP-10 | 按干物计算小数 | 浮点或提前取整 | 万分克整数累计 | `app/modules/dry/weights.py` | `tests/test_dry.py::test_mass_exact_with_fractional_moisture` |
| TRAP-14 | PJ-06 双化验冲突 | 后写覆盖 | 两个原件行均隔离 | `app/modules/assay/service.py` | `tests/test_assay.py::test_contradictory_assays_disable_both` |
| TRAP-15 | PJ-02 克和千克混写 | 重复入库 | 规范成克后判同批 | `app/modules/assay/units.py` | `tests/test_assay.py::test_kg_is_normalized_before_duplicate_detection` |
| TRAP-19 | PJ-02 与 PJ-04 均可配 | 随记录顺序 | 先批数再到期，再按批号 | `app/modules/blend/search.py` | `tests/test_blend.py::test_conflicting_valid_choices_resolve_by_expiry` |
| TRAP-21 | 合桶复验合格但 D-02 含已到期 R-03 | 整桶按复验放行 | 整桶不可领 `EXPIRED_SOURCE`，卡住 5000 g | `app/modules/reuse/service.py` | `tests/test_reuse.py::test_rechecked_drum_still_blocked_by_expired_source` |
| TRAP-22 | 同一原批被多个桶引用 | 每桶各扣一次 | 按提交序只转出一次，超出判 `OVER_SOURCE` | `app/modules/reuse/service.py` | `tests/test_reuse.py::test_unverifiable_sources_are_invalid_and_keep_lots` |
| TRAP-23 | 合桶前后同批重量 | 期初/领用各算一遍 | 期初只按原批，守恒 期初 = 领用 + 期末 | `app/modules/stock/balance.py` | `tests/test_reuse_oracle.py` |
| TRAP-24 | 两单同时领同一桶 | 各自读到旧余量 | 目录文件锁内校验与发布 | `app/modules/ledger/service.py` | `tests/test_issue.py::test_concurrent_issues_never_overdraw_same_drum` |
| TRAP-25 | 失败单重试 | 再扣一次余料 | 失败不落盘；同 `key` 重放返回原记录 | `app/modules/ledger/service.py` | `tests/test_issue.py::test_failed_issue_retry_does_not_double_draw` |

## 对账规则

- 脏样本 16 条正文 = 7 采信 + 7 隔离 + 1 重复表头 + 1 空行。
- PJ-01 和 PJ-02 各取 5000 g。干物 4000+5000=9000 g，凝胶度 (4000×120+5000×180)/9000=153.333 SAG。
- 计划 10000 g = 领用 10000 g + 缺口 0 g。采信库存 27000 g = 领用 10000 g + 期末 17000 g。
- 回用样本：5 桶共 15000 g，来源 13000 g 各从原批转出一次；可回用仅 D-01（5000 g）。D-02 复验合格但 R-03 已到期，可领 0 g。
- 回用样本计划 5000 g = D-01 领用 5000 g + 缺口 0 g。D-01 干物 5000×(1-4.5%)=4775 g，SAG 153.000。
- 原批余量 2000(R-01)+3000(R-02)+2000(R-04)=7000 g；可参与试算 = 原批余量 + 桶余量，合计 12000 g，不重复计合桶来源。
- 桶领用按来源克重分摊，最大余数法保证分摊合计恰等于领用克重，可逐单追到原批。

试算库存源于输入快照。实际出库和电子签章由生产系统处理。本项目使用输入日期裁决有效期。
