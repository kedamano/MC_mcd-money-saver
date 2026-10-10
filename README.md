# 🍔 麦麦省钱助手（McDonald's Money-Saver）

> **麦当劳程序员创意开发大赛参赛作品** · 基于麦当劳中国 MCP 的省钱点餐 Skill
> 一句话自动比券、挑出最优优惠组合、官方核价并下单。

<p align="center">
  <a href="https://github.com/kedamano/mcd-money-saver/stargazers"><img src="https://img.shields.io/github/stars/kedamano/mcd-money-saver?style=social" alt="GitHub Stars"></a>
  <a href="https://github.com/kedamano/mcd-money-saver/actions/workflows/ci.yml"><img src="https://github.com/kedamano/mcd-money-saver/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://github.com/kedamano/mcd-money-saver/issues"><img src="https://img.shields.io/github/issues/kedamano/mcd-money-saver" alt="GitHub issues"></a>
  <img src="https://img.shields.io/badge/license-参赛声明-brightgreen" alt="License">
  <img src="https://img.shields.io/badge/Python-3.11%2B-blue" alt="Python">
  <img src="https://img.shields.io/badge/tests-63%20passed-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/MCP-35%20tools%20live-orange" alt="MCP">
  <img src="https://img.shields.io/badge/Contest-麦当劳MCP大赛-ffc72c" alt="Contest">
</p>

<p align="center">
  <b>⭐ 如果这个项目帮到了你，点个 Star 支持一下，也帮它冲一波大赛排名！</b><br>
  <a href="https://github.com/kedamano/mcd-money-saver">github.com/kedamano/mcd-money-saver</a>
</p>

---

## 🌟 这是什么

「麦麦省钱助手」是一个运行在 [WorkBuddy](https://www.workbuddy.cn) 中的 **Skill（技能）**，
依托**麦当劳中国 MCP Server**（`https://mcp.mcd.cn`，35 个真实工具）的能力，帮你在点麦当劳时
**自动完成**：选门店 → 拉菜单 → 收三池优惠券 → 算最优组合 → 官方核价 → 一键下单。

你只需要说一句话，剩下的比券、凑单、算账它全包了。

---

## 📊 真实数据说话（不是 Demo，是真连）

本项目**真实接入麦当劳 MCP**，并通过 WorkBuddy MCP 通道跑通了端到端链路（2026-10-10 实测）：

| 环节 | 工具 | 真实结果 |
|---|---|---|
| 取时间 | `now-time-info` | 返回服务器时间（GMT+8）✅ |
| 搜门店 | `query-nearby-stores` | 上海南京东路 5 家，最近 194m ✅ |
| 拉菜单 | `query-meals` | 全分类现价（巨无霸 ¥25.5 / 中薯条 ¥13.5 …）✅ |
| 查券 | `query-store-coupons` | 2 张新人券：美式7折 / 奶铁7折 ✅ |
| 核价 | `calculate-price` | 见下 ✅ |

### 💰 真实核价对比（金额单位：分，来自官方 `calculate-price`）

| 场景 | 购物车 | 原价 | 用券后 | **省** |
|---|---|---|---|---|
| 美式中杯7折券 | 美式中杯 + 巨无霸 + 中薯条 | ¥58.00 | **¥52.30** | **¥5.70** |

> 美式中杯 ¥19.00 × 0.7 = ¥13.30，与券面"7 折"**完全吻合**，`discount=570` 分，服务端权威价与本地计算一致。
> 更妙的是：美式中杯是**券锁定商品**——没券时 `calculate-price` 会直接把它踢出订单。这正是本 Skill 用 `product_codes` 做"券↔商品"精确绑定的现实依据。

**自动化验证**：`pytest` 回归 **67 passed（离线 63 + 真实 live 4；另有 1 例真实下单受保护、默认跳过）**。其中 `test_live_end_to_end` 走项目自带 Python 客户端（`mcd_client.py`，纯标准库）真实连通 `initialize → list_tools(35) → now-time-info`；`test_live_calibration` 用真实返回值校准本地价格模型与官方一致；`test_scale_pruning` / `test_topk_pruning` 以 40 组随机用例证明**分支限界与暴力枚举同解**（单最优 + Top-K 两条路径）。

> 🎬 **想看完整真实链路？** 运行 `MCD_MCP_TOKEN=xxx python examples/demo_live.py`，
> 一条命令跑通「时间 → 门店 → 菜单 → 优惠券 → 官方核价」，样例输出见 [`DEMO.md`](DEMO.md)。

---

## 🏗️ 端到端架构

```mermaid
flowchart LR
    U["💬 用户一句话<br/>『帮我点麦当劳怎么最省』"] --> S["🤖 WorkBuddy<br/>麦麦省钱助手 Skill"]
    S --> C["🎫 收券·三池并集<br/>门店券 + 我的券 + 麦麦省券"]
    S --> M["🏪 选门店 / 拉菜单<br/>query-nearby-stores · query-meals"]
    C --> O["🧮 本地优化器<br/>暴力枚举 / 分支限界 → Top-K 候选"]
    O --> V["✅ 官方核价<br/>calculate-price 取权威价"]
    V --> R["📋 最低到手价 + 用券明细"]
    R --> D["🛒 确认 → create-order 下单"]

    style U fill:#ffc72c,stroke:#d4a017,color:#000
    style S fill:#1e88e5,stroke:#0d47a1,color:#fff
    style V fill:#43a047,stroke:#1b5e20,color:#fff
    style D fill:#fb8c00,stroke:#e65100,color:#fff
```

### 🔍 两阶段核价模型（为什么结果可信）

很多"比券工具"只算本地、下单才发现不对。本 Skill 用**两阶段**堵住这个坑：

| 阶段 | 做什么 | 特点 |
|---|---|---|
| **① 本地求解（毫秒级）** | 小券池（≤16 张）暴力枚举所有叠加组合；大券池自动切**分支限界**（先剔 0 优惠券，再按乐观上界剪枝），在「门槛校验 + 订单级券至多一张 + 免配送费券至多一张」约束下求 Top-K 最低价候选 | 0 网络开销；券数大也可扩展 |
| **② 官方核价（权威）** | 仅对 Top-K 候选调用麦当劳 `calculate-price`，取官方返回的真实价 | 以官方为准，杜绝"算得美、下单贵" |

> 实测：阶段①本地最优与阶段②官方核价**完全一致**（美式 7 折 19×0.7=13.30），模型与服务端真实行为对齐。

---

## ✨ 功能亮点

| 能力 | 说明 |
|---|---|
| 多池并集比券 | 门店券、我的券、麦麦省券三池聚合；**真机实测三池返回结构不同**（门店券为结构化 JSON 可核价，我的券/麦麦省券为 Markdown 需解析），按券名去重、标注可领取扩池 |
| 最优叠加组合 | 满减 / 折扣 / 立减 / 免配送费 自动求最低价；**大券池走分支限界**（n=20 时较暴力枚举快 ~260×，与暴力枚举**同解**）|
| 类目 & 互斥约束 | 支持类目限定券；订单级券至多一张，贴合真实规则 |
| 🅱️ **产品级绑定** | 券按 `product_codes` 精确匹配，错配自动失效（券锁定商品也能正确处理）|
| 🅲️ **凑单建议** | 距满减门槛差 X 元时，反推最小代价加购组合，净亏不推 |
| 🅳️ **两阶段核价** | 本地枚举 Top-K → 仅少量候选调官方 `calculate-price` 取权威价 |
| 🅴️ **时效与库存** | 过期券自动剔除、**未生效/每日时段窗**（如仅 05:00-23:59 可用）校验、不可售商品提示移出优惠范围 |
| 官方核价兜底 | 用 `calculate-price` 校验，避免"算得美、下单贵" |
| 一键领券扩池 | `auto-bind-coupons` 自动领取麦麦省券再比价 |
| 🛡️ **健壮性** | MCP 偶发 404/5xx/429 **自动重试 + 熔断**（下单等副作用调用禁用重试）；门店/菜单/券 **TTL 缓存**；`scripts/doctor.py` 一键排查配置坑 |

---

## 🚀 WorkBuddy 一键使用

### 1️⃣ 接入麦当劳 MCP（复制粘贴即可）

左侧 **【专家·技能·连接器】→【连接器】→【自定义连接器】→【配置 MCP】**，粘贴：

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamable-http",
      "url": "https://mcp.mcd.cn",
      "headers": {
        "Authorization": "Bearer ${MCD_MCP_TOKEN}"
      }
    }
  }
}
```

> ⚠️ **`type` 必须是 `streamable-http`（带连字符）**，否则会卡在"需要认证"无法连接。
> Token 来自 https://open.mcd.cn/mcp （手机号登录 → 控制台 → 激活 → 复制）。**严禁将真实 Token 提交进仓库**，仓库内仅保留脱敏示例 `mcp-config.example.json`。

### 2️⃣ 安装本 Skill

将本仓库克隆后，把 `SKILL.md` 与 `src/` 放入 WorkBuddy 的**用户技能目录**（参考 WorkBuddy 官方文档的 Connector / Skill 说明），或在对话中直接引用本仓库的 `SKILL.md`。

### 3️⃣ 开聊（三种触发都是它）

在 WorkBuddy 对话框里直接说：

- "帮我点一份麦当劳，怎么最省钱？"
- "附近麦当劳有什么优惠券能用，帮我凑个最划算的套餐"
- "我想点巨无霸+薯条+可乐，外送到家，帮我比券"

助手会自动走完 **选店 → 选品 → 比券 → 核价 → 下单** 全流程，并汇报：
`原价 ¥71.0 → 用券后 ¥54.0，省 ¥17.0（组合：满60减12 + 小食减5）`。

---

## 🧪 本地验证（无需 Token）

核心算法与真实接口解析均可离线测试，不依赖麦当劳 MCP：

```bash
python -m pytest tests/ -q                 # 离线：63 例全过（含真实合同测试）
python scripts/doctor.py                   # 环境自检：查 mcp.json 的 type / Token 前缀
python src/coupon_optimizer.py             # 内置演示（基础优化器）
python examples/demo_smart.py              # B/C/D/E 离线演示
MCD_MCP_TOKEN=xxx pytest -m live -q        # 可选：真实端到端冒烟（initialize→list_tools→call_tool）
MCD_MCP_TOKEN=xxx python examples/demo_live.py           # ⭐ 真实端到端演示（选店→拉券→官方核价）
MCD_MCP_TOKEN=xxx python examples/demo_smart.py --live   # D 两阶段真实官方核价演示
```

---

## 📁 仓库结构

```
mcd-money-saver/
├── SKILL.md                    # WorkBuddy Skill 定义（省钱工作流）
├── README.md                   # 本文件
├── SPEC.md                     # 规格说明书（SDD，含真实业务规则与验收标准）
├── CONTEST_DECLARATION.md      # 参赛声明（官方原文，不可改）
├── MCP_INTEGRATION.md          # 麦当劳 MCP 集成说明
├── mcp-config.example.json     # 脱敏 MCP 配置示例（仅环境变量占位符）
├── LIVE_TEST_LOG.md            # 真实 MCP 端到端测试报告
├── DEMO.md                     # 真实端到端演示样例输出（可截图）
├── workbuddy.md                # WorkBuddy 联动开发上下文（专项奖励核验）
├── src/
│   ├── coupon_optimizer.py     # 最优组合优化器（暴力枚举 / 分支限界双策略 + B/E + rank_candidates）
│   ├── coupon_adapter.py       # 真实券 JSON -> 领域 Coupon（含 product_codes/expires_at）
│   ├── coupon_pools.py         # 三池聚合：门店券(JSON) / 我的券 / 麦麦省券(Markdown) 解析
│   ├── coupon_smart.py         # C 凑单建议 + D 两阶段校验（智能决策增强）
│   └── mcd_client.py           # 麦当劳 MCP 真实客户端（含 price_combo 官方核价）
├── tests/
│   ├── test_coupon_optimizer.py# TDD 测试契约（基础优化器）
│   ├── test_enhancements.py    # B/C/D/E 契约测试
│   ├── test_real_contract.py   # 真实合同测试（基于 fixtures 黄金基准）
│   ├── test_coupon_pools.py    # 三池 Markdown 解析 + 聚合测试
│   ├── test_time_window.py     # 生效时间 / 每日时段窗过滤测试
│   ├── test_scale_pruning.py   # 大规模券剪枝 + 分支限界（与暴力枚举同解 + 性能）
│   ├── test_topk_pruning.py    # Top-K 候选的分支限界（rank_candidates 与暴力枚举同值）
│   ├── test_live_calibration.py# 本地价格模型 vs 官方核价（live 校准）
│   ├── test_mcd_client.py      # 客户端解析单测 + 可选真实冒烟(-m live)
│   └── fixtures/               # 真实 calculate-price 返回 + 真实菜单目录（脱敏）
├── examples/
│   ├── demo_smart.py           # B/C/D/E 端到端演示（离线 / --live）
│   └── demo_live.py            # ⭐ 真实 MCP 端到端演示（选店→拉券→官方核价）
├── .github/workflows/ci.yml    # GitHub Actions：每次 push 自动跑离线测试
├── scripts/
│   └── doctor.py               # 环境自检：排查 mcp.json type / Token 前缀 / 握手
├── conftest.py / pytest.ini    # pytest 路径与标记配置
└── references/
    └── mcp_tools.md            # 省钱场景 MCP 工具参考
```

---

## 📜 免责声明

本项目为麦当劳程序员节创意开发大赛**参赛作品**，由作者独立开发，**非麦当劳官方产品**。
项目输出仅供参考，餐品信息、价格及供应状态以麦当劳官方渠道实时结果为准；不构成
医疗、营养或其他专业建议。详见 `CONTEST_DECLARATION.md`。

---

<p align="center">
  <b>🍔 觉得有用？<a href="https://github.com/kedamano/mcd-money-saver">点个 Star</a> 支持作者冲大赛排名！</b>
</p>
