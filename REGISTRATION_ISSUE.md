# 报名 Issue（复制到 GitHub 活动仓库的 New Issue）

> 使用方式：在 https://github.com/M-China/mcd-developer-innovation-challenge 点击 "New Issue"，
> 把下面「Issue 标题」和「Issue 正文」分别填到标题框和正文框，**纯文本、不插图**。
>
> ✅ **仓库名已从 `MC_mcd-money-saver` 改为 `mcd-money-saver`（纯小写、mcd 开头）**。
> 原因：官方审核脚本大概率用"只匹配小写/连字符"的正则从正文解析仓库地址，遇到大写 `MC_` 和下划线会提取失败 → 误判"项目无法访问"。改名已彻底消除该隐患（已实证：新名公开可访问，旧名自动重定向）。

## Issue 标题
麦麦省钱助手：基于麦当劳 MCP 的最优省钱点单 Skill

## Issue 正文
【参赛申请】
项目名称：麦麦省钱助手（mcd-money-saver）
项目地址：https://github.com/kedamano/mcd-money-saver
项目简介：
麦麦省钱助手是一款基于麦当劳中国 MCP Server 开发的 WorkBuddy Skill，帮助用户在麦当劳点单时自动聚合"麦麦省券""门店券""我的券"等多来源优惠券，结合真实菜单与门店数据，智能计算最优凑单与组合方案，最大化优惠力度。

核心能力：
1. 真实接入麦当劳 MCP（35 个工具），调用 available-coupons / query-my-coupons / query-store-coupons / query-nearby-stores / query-meals / calculate-price 完成选券、核价与门店查询；
2. 多券种兼容引擎：支持满减、折扣、立减、免配送费券，自动处理互斥与叠加规则；
3. 智能凑单建议：在"差一点满减"时推荐高性价比加购，量化净收益；
4. 两阶段校验：本地 Top-K 候选 + 官方 calculate-price 二次核价，结果以官方为准；
5. 过期券自动剔除、商品售罄过滤，保证方案可落地。

项目遵循 SDD+TDD 开发，含离线契约测试与真实 MCP 联调用例，可直接在 WorkBuddy 中通过对话指令使用。
