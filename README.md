# 麦麦省钱助手（McDonald's Money-Saver）

> 麦当劳程序员创意开发大赛参赛作品 · 基于麦当劳中国 MCP 的省钱点餐 Skill
> 一句话自动比券、挑出最优优惠组合、核价并下单。

[![License: 参赛作品](https://img.shields.io/badge/license-参赛声明-brightgreen)]()

---

## 项目简介

「麦麦省钱助手」是一个运行在 [WorkBuddy](https://www.workbuddy.cn) 中的 Skill，
依托**麦当劳中国 MCP Server**（`https://mcp.mcd.cn`）真实能力，帮用户在点到餐时
自动完成：

1. **选门店**（到店 / 外送）
2. **选品**（拉取门店菜单，构造购物项）
3. **收券**（并集「门店券 + 我的券 + 麦麦省券」三池优惠券）
4. **比券择优**（暴力枚举所有可叠加组合，输出最低到手价）
5. **官方核价**（`calculate-price` 二次校验，结果可信）
6. **确认下单**（`create-order` 获取支付链接）

核心省钱逻辑由纯函数模块 `src/coupon_optimizer.py` 实现，已被 10 个单元测试覆盖（TDD）。

## 目标用户

- 经常点麦当劳、想"薅羊毛"但懒得逐张比券的普通消费者
- 想用最少操作凑出最划算套餐的性价比用户
- 对麦当劳 MCP / Agent 开发感兴趣、想参考实战落地方案的开发者

## 功能亮点

| 能力 | 说明 |
|---|---|
| 多池并集比券 | 门店券、我的券、麦麦省券一次性纳入候选 |
| 最优叠加组合 | 满减 / 折扣 / 立减 / 免配送费 自动求最低价 |
| 类目 & 互斥约束 | 支持类目限定券；订单级券至多一张，贴近真实规则 |
| 官方核价兜底 | 用 `calculate-price` 校验，避免"算得美、下单贵" |
| 一键领券扩池 | `auto-bind-coupons` 自动领取麦麦省券再比价 |

## 安装与配置

### 1. 申请麦当劳 MCP Token
前往 https://open.mcd.cn/mcp ，手机号登录 → 控制台 → 激活 → 复制 Token。

### 2. 在 WorkBuddy 中接入 mcd-mcp
左侧【专家·技能·连接器】→【连接器】→【自定义连接器】→【配置 MCP】，粘贴：

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": {
        "Authorization": "Bearer ${MCD_MCP_TOKEN}"
      }
    }
  }
}
```

> ⚠️ 把 `YOUR_MCD_MCP_TOKEN` 换成你的真实 Token，或设置环境变量 `MCD_MCP_TOKEN` 后使用占位符。
> **严禁将真实 Token 提交进仓库。** 仓库内仅提供脱敏示例 `mcp-config.example.json`。

### 3. 安装本 Skill
将本仓库克隆后，把 `SKILL.md` 与 `src/` 放入 WorkBuddy 的用户技能目录
（参考 WorkBuddy 官方文档的 Connector / Skill 说明），或在对话中直接引用本仓库的 SKILL.md。

## 使用示例

在 WorkBuddy 对话框中直接说：

- "帮我点一份麦当劳，怎么最省钱？"
- "附近麦当劳有什么优惠券能用，帮我凑个最划算的套餐"
- "我想点巨无霸+薯条+可乐，外送到家，帮我比券"

助手会自动走完选店 → 选品 → 比券 → 核价 → 下单流程，并汇报：
`原价 ¥71.0 → 用券后 ¥54.0，省 ¥17.0（组合：满60减12 + 小食减5）`。

## 本地验证（无需 Token）

核心算法可独立测试，不依赖麦当劳 MCP：

```bash
python -m pytest tests/ -q
python src/coupon_optimizer.py   # 内置演示
```

## 仓库结构

```
mcd-money-saver/
├── SKILL.md                    # WorkBuddy Skill 定义（省钱工作流）
├── README.md                   # 本文件
├── CONTEST_DECLARATION.md      # 参赛声明（官方原文，不可改）
├── MCP_INTEGRATION.md          # 麦当劳 MCP 集成说明
├── mcp-config.example.json     # 脱敏 MCP 配置示例（仅环境变量占位符）
├── workbuddy.md                # WorkBuddy 联动开发上下文（专项奖励核验）
├── src/
│   ├── __init__.py
│   └── coupon_optimizer.py     # 优惠券最优组合优化器（核心源码）
├── tests/
│   └── test_coupon_optimizer.py# TDD 测试契约（10 例全过）
├── conftest.py                 # pytest 路径配置
└── references/
    └── mcp_tools.md            # 省钱场景 MCP 工具参考
```

## 免责声明

本项目为麦当劳程序员节创意开发大赛**参赛作品**，由作者独立开发，**非麦当劳官方产品**。
项目输出仅供参考，餐品信息、价格及供应状态以麦当劳官方渠道实时结果为准；不构成
医疗、营养或其他专业建议。详见 `CONTEST_DECLARATION.md`。
