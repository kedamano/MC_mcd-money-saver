# workbuddy.md — WorkBuddy 联动开发上下文

> 本文件按《麦当劳程序员创意开发大赛》要求导出，用于核验本项目是否真实使用
> 腾讯 WorkBuddy 智能体进行开发，以参与 WorkBuddy 专项奖励（排行榜前 100 名且提交本文件可得 3000 积分）。

## 开发环境

- 智能体：**腾讯 WorkBuddy**（官方合作伙伴）
- 运行时：Windows 11，Python 3.13（隔离 venv），Node 22（managed）
- 开发方式：在 WorkBuddy 对话中完成"读需求 → 定方案 → TDD 实现 → 测试 → 产出交付物"全流程

## 对话上下文概要（关键节点）

1. **需求研读**
   - 用户指令："阅读这个项目，我要按照要求进行开发"，链接 https://github.com/M-China/mcd-developer-innovation-challenge
   - WorkBuddy 通过 WebFetch 读取了主仓库 README、activityGuidelines.md、CONTEST_DECLARATION.md，
     以及麦当劳 MCP Server 仓库（工具列表、接入方式、错误码）。
   - 提炼出硬性交付物清单（README / CONTEST_DECLARATION / MCP_INTEGRATION /
     mcp-config.example.json / workbuddy.md / 源码）与时间窗、Star 排名规则。

2. **方案决策（AskUserQuestion）**
   - 方向：麦麦省钱助手（优惠券最优组合）
   - 形态：WorkBuddy Skill（SKILL.md + src/ 辅助脚本）
   - Token：用户已有麦当劳 MCP Token，支持真机联调

3. **TDD 实现**
   - 先写 `tests/test_coupon_optimizer.py`（10 个测试契约：满减、折扣封顶、免配送费、
     互斥券、组合择优、类目限制、无券场景等）。
   - 再实现 `src/coupon_optimizer.py`：暴力枚举券子集 + 约束剪枝（门槛校验、订单级券至多一张、
     免配送费券互斥、类目限定）。
   - 首轮测试暴露建模缺陷（折扣券与满减券被错误叠加，得 47.5 而非合理值），修正为
     "全单通用型订单级券至多一张"的真实约束后，**10/10 测试通过**，演示输出
     `原价 71 → 用券后 54，省 17（满60减12 + 小食减5）`。

4. **Skill 与文档产出**
   - 加载 WorkBuddy 官方 `skill-creator` 规范，生成符合平台格式的 `SKILL.md`
     （frontmatter 含 `name` / `description` / `agent_created: true`，祈使句工作流，
      绑定麦当劳 MCP 工具与 `coupon_optimizer` 脚本）。
   - 编写 `MCP_INTEGRATION.md`（实际调用 Tool 清单、调用流程、业务价值）、
     `mcp-config.example.json`（仅环境变量占位符）、`README.md`、`CONTEST_DECLARATION.md`
     （官方原文不可改）、`references/mcp_tools.md`。

## 真实性佐证

- 项目核心算法 `src/coupon_optimizer.py` 由 WorkBuddy 在对话中编写并通过 `pytest` 验证。
- 所有交付文件均按活动规则命名与组织，未包含任何真实 Token/密钥（仅 `${MCD_MCP_TOKEN}` 占位符）。
- 本项目真实接入并使用麦当劳中国 MCP（`https://mcp.mcd.cn`）的优惠/菜单/下单能力。

---
*导出说明：本文件为参赛核验用途，记录了 WorkBuddy 辅助开发的真实过程。*
