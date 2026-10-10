# -*- coding: utf-8 -*-
"""生成 README 视觉素材（可复现，纯本地渲染，不依赖网络）。

产物（写入 docs/assets/）：
    - hero.svg          顶部主视觉横幅
    - architecture.svg  端到端精修架构图
    - pipeline-live.gif 真实链路终端实录（逐行打字动画）
    - terminal-live.png 真实链路静态截图（终端最后一帧）

运行：
    python scripts/build_assets.py
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "docs", "assets")
os.makedirs(OUT, exist_ok=True)

# ---------------------------------------------------------------- 通用配色
INK = "#1F2328"
MUTED = "#57606A"
BORDER = "#D0D7DE"
SOFT = "#F6F8FA"
RED = "#DA291C"
YELLOW = "#FFC72C"
YELLOW_T = "#9A6A00"
GREEN = "#1A7F37"
BLUE = "#0969DA"
PURPLE = "#8250DF"

FONT_STACK = (
    "-apple-system,BlinkMacSystemFont,'Segoe UI','Microsoft YaHei',"
    "'PingFang SC','Hiragino Sans GB',sans-serif"
)


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def rrect(x, y, w, h, fill, stroke=None, rx=12, sw=1.2, extra=""):
    s = f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"'
    if stroke:
        s += f' stroke="{stroke}" stroke-width="{sw}"'
    return s + f' {extra}/>'


def text(x, y, s, size=14, color=INK, weight="400", anchor="start", ls=0, extra=""):
    ls_attr = f' letter-spacing="{ls}"' if ls else ""
    return (
        f'<text x="{x}" y="{y}" font-size="{size}" fill="{color}" '
        f'font-weight="{weight}" text-anchor="{anchor}"{ls_attr} {extra}>{esc(s)}</text>'
    )


def arrow_defs(color=BORDER):
    return (
        "<defs>"
        f'<marker id="arw" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" '
        f'markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{color}"/></marker>'
        "</defs>"
    )


def svg_wrap(w, h, body, bg="#FFFFFF"):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'viewBox="0 0 {w} {h}" font-family="{FONT_STACK}">'
        f'<rect width="{w}" height="{h}" fill="{bg}"/>'
        f"{body}</svg>"
    )


# ================================================================ 1. HERO
def build_hero() -> str:
    W, H = 1200, 300
    b = []
    # 左侧品牌色块
    b.append(rrect(0, 0, 14, H, RED, rx=0))
    b.append(rrect(14, 0, 8, H, YELLOW, rx=0))
    # 标题
    b.append(text(60, 104, "麦麦省钱助手", size=52, weight="800", ls=1))
    b.append(text(60, 148, "McDonald's Money-Saver", size=22, color=RED, weight="700", ls=2))
    b.append(text(60, 186, "基于麦当劳中国 MCP 的最优省钱点单 Skill", size=18, color=MUTED))
    b.append(
        text(
            60,
            218,
            "三池券聚合 · 最优凑单 · 官方真实核价 · 到店 / 外送双场景",
            size=16,
            color=BLUE,
            weight="600",
        )
    )
    b.append(
        text(
            60,
            258,
            "WorkBuddy Skill · 麦当劳程序员创意开发大赛参赛作品",
            size=13,
            color="#8B949E",
        )
    )
    # 右侧统计卡
    stats = [
        ("35", "MCP 真实工具"),
        ("95", "自动化用例"),
        ("4 城", "真实核价实测"),
        ("¥6.30", "单杯最高省"),
    ]
    x0, y0, cw, ch, gap = 640, 62, 130, 82, 14
    for i, (num, label) in enumerate(stats):
        cx = x0 + (i % 2) * (cw + gap)
        cy = y0 + (i // 2) * (ch + gap)
        b.append(rrect(cx, cy, cw, ch, SOFT, BORDER, rx=12))
        b.append(text(cx + cw / 2, cy + 40, num, size=26, weight="800", color=RED, anchor="middle"))
        b.append(text(cx + cw / 2, cy + 66, label, size=13, color=MUTED, anchor="middle"))
    # 右下角冲榜角标
    b.append(rrect(x0, 244, 2 * cw + gap, 40, "#FFF8E1", YELLOW, rx=10))
    b.append(
        text(
            x0 + cw + gap / 2,
            270,
            "⭐ Star 支持一下，帮它冲一波大赛排名",
            size=14,
            weight="700",
            color=YELLOW_T,
            anchor="middle",
        )
    )
    return svg_wrap(W, H, "".join(b))


# ====================================================== 2. ARCHITECTURE
def build_architecture() -> str:
    W, H = 1240, 790
    b = [arrow_defs()]
    b.append(text(40, 52, "端到端架构 · 麦麦省钱助手", size=25, weight="800"))
    b.append(
        text(
            40,
            80,
            "WorkBuddy Skill  →  纯标准库 MCP 客户端  →  麦当劳 MCP 网关（35 tools）  →  官方核价 / 下单",
            size=14,
            color=MUTED,
        )
    )

    LX, LW = 40, 118          # 左侧层标签
    MX, MW = 176, 830         # 主列
    RX, RW = 1026, 178        # 右侧亮点列

    def layer_label(y, h, name):
        b.append(rrect(LX, y, LW, h, SOFT, BORDER, rx=10))
        b.append(text(LX + LW / 2, y + h / 2 + 5, name, size=14, weight="700",
                      color=INK, anchor="middle"))

    def vdown(x, y1, y2, color=BORDER):
        b.append(f'<path d="M {x} {y1} L {x} {y2}" stroke="{color}" stroke-width="2" '
                 f'marker-end="url(#arw)" fill="none"/>')

    # A 用户层
    ay, ah = 104, 60
    layer_label(ay, ah, "用户层")
    b.append(rrect(MX, ay, MW, ah, "#FFF8E1", YELLOW, rx=12))
    b.append(text(MX + MW / 2, ay + 38, "用户一句话：「帮我点最省的麦当劳」",
                  size=18, weight="700", color=YELLOW_T, anchor="middle"))

    # B Skill 层
    by, bh = 192, 116
    layer_label(by, bh, "Skill 层")
    cards = [
        ("SKILL 编排", "SKILL.md 工作流", "#F3F0FF", PURPLE),
        ("三池券聚合", "coupon_pools", "#EAF6FF", BLUE),
        ("优化器", "coupon_optimizer", "#FFEFED", RED),
        ("券↔商品适配", "coupon_adapter", "#EAFBF0", GREEN),
    ]
    cw = (MW - 3 * 14) / 4
    for i, (t, sub, fill, accent) in enumerate(cards):
        cx = MX + i * (cw + 14)
        b.append(rrect(cx, by, cw, bh, fill, accent, rx=12, sw=1.4))
        b.append(rrect(cx, by, cw, 5, accent, rx=0))
        b.append(text(cx + cw / 2, by + 52, t, size=16, weight="800", color=INK, anchor="middle"))
        b.append(text(cx + cw / 2, by + 78, sub, size=13, color=MUTED, anchor="middle"))
    vdown(MX + MW / 2, ay + ah, by)

    # C 客户端层
    cy, chh = 340, 72
    layer_label(cy, chh, "客户端层")
    b.append(rrect(MX, cy, MW, chh, "#EAF6FF", BLUE, rx=12, sw=1.4))
    b.append(text(MX + 24, cy + 30, "mcd_client.py · 纯标准库 MCP 客户端",
                  size=16, weight="800", color=INK))
    b.append(text(MX + 24, cy + 55,
                  "握手 initialize · 指数退避重试 · 熔断（副作用调用）· TTL 缓存",
                  size=13, color=MUTED))
    vdown(MX + MW / 2, by + bh, cy)

    # D MCP 网关
    dy, dh = 444, 64
    layer_label(dy, dh, "MCP 网关")
    b.append(rrect(MX, dy, MW, dh, "#FFF3E0", "#E8A33D", rx=12, sw=1.4))
    b.append(text(MX + MW / 2, dy + 28,
                  "麦当劳中国 MCP Server    https://mcp.mcd.cn",
                  size=16, weight="800", color="#8A4B08", anchor="middle"))
    b.append(text(MX + MW / 2, dy + 50,
                  "35 个真实工具 · Authorization: Bearer <token>",
                  size=13, color="#A15C11", anchor="middle"))
    vdown(MX + MW / 2, cy + chh, dy)

    # E 业务能力
    ey, eh = 540, 92
    layer_label(ey, eh, "业务能力")
    caps = [
        ("门店查询", "query-nearby-stores"),
        ("菜单取价", "query-meals"),
        ("三池券", "query-store-coupons"),
        ("官方核价", "calculate-price"),
        ("下单", "create-order"),
    ]
    w5 = (MW - 4 * 12) / 5
    for i, (c, tool) in enumerate(caps):
        cx = MX + i * (w5 + 12)
        b.append(rrect(cx, ey, w5, eh, SOFT, BORDER, rx=12))
        b.append(text(cx + w5 / 2, ey + 40, c, size=15, weight="700", color=INK, anchor="middle"))
        b.append(text(cx + w5 / 2, ey + 63, tool, size=9.5, color=MUTED, anchor="middle"))
    vdown(MX + MW / 2, dy + dh, ey)

    # F 输出
    fy, fh = 664, 66
    layer_label(fy, fh, "输出")
    b.append(rrect(MX, fy, MW, fh, "#EAFBF0", GREEN, rx=12, sw=1.4))
    b.append(text(MX + MW / 2, fy + 40,
                  "官方核价结果 · 最优优惠组合 · 一键下单（生成订单）",
                  size=17, weight="800", color="#0F5C2A", anchor="middle"))
    vdown(MX + MW / 2, ey + eh, fy)

    # ---- 右侧亮点列
    b.append(rrect(RX, by, RW, 132, "#FFEFED", RED, rx=12, sw=1.2))
    b.append(text(RX + 16, by + 30, "优化器内核", size=15, weight="800", color=RED))
    for i, s in enumerate(["暴力枚举（基准）", "分支限界 B & B", "Top-K 候选堆", "拆单策略优化"]):
        b.append(text(RX + 16, by + 56 + i * 20, "· " + s, size=12.5, color=INK))

    b.append(rrect(RX, by + 148, RW, 176, "#EAF6FF", BLUE, rx=12, sw=1.2))
    b.append(text(RX + 16, by + 178, "真机才挖到的规则", size=15, weight="800", color=BLUE))
    rules = [
        "每单至多一张券",
        "券锁定商品、无券剔除",
        "外送全程必传 beCode",
        "券有到店 / 外送渠道限制",
        "同品不同城不同价",
        "折扣与券面精确吻合",
    ]
    for i, s in enumerate(rules):
        b.append(text(RX + 16, by + 204 + i * 20, "· " + s, size=12, color=INK))

    b.append(rrect(RX, by + 340, RW, 148, "#EAFBF0", GREEN, rx=12, sw=1.2))
    b.append(text(RX + 16, by + 370, "工程可信度", size=15, weight="800", color=GREEN))
    for i, s in enumerate(["95 项自动化用例", "CI 双版本 py3.11/3.13", "40 组与暴力同解校验", "分支限界 n=20 快 ~260×"]):
        b.append(text(RX + 16, by + 396 + i * 20, "· " + s, size=12, color=INK))

    return svg_wrap(W, H, "".join(b))


# ================================================= 3. 终端实录（GIF/PNG）
# 真实运行 examples/demo_live.py 的原始输出（2026-10-10 14:22，上海食品/悦荟广场店）
LINES = [
    ("sep", "============================================================"),
    ("title", "  麦麦省钱助手 · 真实麦当劳 MCP 端到端演示"),
    ("dim", "  数据源：https://mcp.mcd.cn（真实生产网关）"),
    ("sep", "============================================================"),
    ("ok", "[1/5] 服务器时间   2026-10-10 14:22:10  SATURDAY  GMT+08:00"),
    ("ok", "[2/5] 附近门店     1450104 麦当劳上海黄浦悦荟广场餐厅（194m）"),
    ("ok", "[3/5] 门店菜单     共 123 个商品 / 15 个分类"),
    ("dim", "                    - 巨无霸 ¥25.50"),
    ("dim", "                    - 中薯条 ¥13.50"),
    ("dim", "                    - 可乐 ¥9.50"),
    ("ok", "[4/5] 三池券聚合   门店券 2 · 我的券 2 · 可领麦麦省券 6"),
    ("hl", "      [门店券·可核价] 新人专享-中杯美式7折（适用：美式中杯）"),
    ("hl", "      [门店券·可核价] 新人专享-中杯奶铁7折（适用：奶铁中杯）"),
    ("hl", "      [我的券·展示]  中杯美式7折  ¥13.3 (用券价)  到店专用"),
    ("dim", "      [麦麦省·可领取] 免费脆薯饼 / 麦旋风买一送一 / 9.9 中杯冰美式"),
    ("dim", "      重叠（门店券∩我的券）：中杯美式7折、中杯奶铁7折"),
    ("warn", "      ⚠️ 6 张『麦麦省』券可领取，auto-bind 后券池可能扩大"),
    ("ok", "[5/5] 官方核价对比（calculate-price）"),
    ("dim", "      购物车：美式中杯 + 巨无霸 + 中薯条   券：中杯美式7折"),
    ("dim", "      ├ 无券   ¥39.00  （美式中杯为券锁定商品，无券被静默剔除）"),
    ("save", "      └ 用券   ¥52.30  （含美式中杯 ¥13.30，券优惠 -¥5.70）"),
    ("save", "      结论：中杯美式 19.00 → 13.30，净省 ¥5.70"),
    ("sep", "------------------------------------------------------------"),
    ("done", "✅ 全链路数据均来自麦当劳 MCP 真实返回（非模拟）"),
]

T_COLOR = {
    "sep": "#58A6FF",
    "title": "#FFC72C",
    "dim": "#9AA4B2",
    "ok": "#56D364",
    "hl": "#C9D1D9",
    "warn": "#E3B341",
    "save": "#FFD866",
    "done": "#56D364",
}

TW, TH = 1180, 668
T_BAR = 42
T_BG = (13, 17, 23)
T_BAR_C = (22, 27, 34)
T_BORDER = (48, 54, 61)

_ASCII = "C:/Windows/Fonts/consola.ttf"
_ASCIIB = "C:/Windows/Fonts/consolab.ttf"
_CJK = "C:/Windows/Fonts/msyh.ttc"
_CJKB = "C:/Windows/Fonts/msyhbd.ttc"
_EMOJI = "C:/Windows/Fonts/seguiemj.ttf"


def _pick(*paths):
    for p in paths:
        if os.path.exists(p):
            return p
    raise FileNotFoundError(paths)


FS = 17
F_ASCII = ImageFont.truetype(_pick(_ASCII), FS)
F_CJK = ImageFont.truetype(_pick(_CJK), FS)
F_CJK_TITLE = ImageFont.truetype(_pick(_CJKB), FS)
F_EMOJI = ImageFont.truetype(_pick(_EMOJI), FS)
F_UI = ImageFont.truetype(_pick(_CJK), 14)


def _is_emoji(o: int) -> bool:
    """仅把真正的符号/表情码位交给 emoji 字体，避免误吃中文（U+4E00+）。"""
    return (
        0x2600 <= o <= 0x27BF      # 杂项符号 / 装饰符号（含 ⚠ ✅）
        or 0x2B00 <= o <= 0x2BFF   # 含 ⭐
        or 0x1F000 <= o <= 0x1FAFF  # 表情象形
        or 0xFE0F == o
    )


def draw_mono(draw, x, y, s, color, cjk_bold=False):
    cjk = F_CJK_TITLE if cjk_bold else F_CJK
    for ch in s:
        o = ord(ch)
        if o in (0xFE0F, 0xFE0E):
            continue
        if o < 128:
            draw.text((x, y), ch, font=F_ASCII, fill=color)
            x += F_ASCII.getlength(ch)
        elif _is_emoji(o):
            draw.text((x, y), ch, font=F_EMOJI, fill=color)
            x += FS + 2
        else:
            draw.text((x, y), ch, font=cjk, fill=color)
            x += cjk.getlength(ch)
    return x


def render_terminal(visible: int, cursor_on: bool, blink_alpha=True) -> Image.Image:
    """渲染终端：显示前 visible 行。"""
    im = Image.new("RGB", (TW, TH), T_BG)
    d = ImageDraw.Draw(im)
    # 标题栏
    d.rectangle([0, 0, TW, T_BAR], fill=T_BAR_C)
    d.line([0, T_BAR, TW, T_BAR], fill=T_BORDER, width=1)
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse([18 + i * 22, 15, 32 + i * 22, 29], fill=c)
    d.text((TW // 2 - 210, 13), "MCD_MCP_TOKEN=*** python examples/demo_live.py",
           font=F_UI, fill=(139, 148, 158))

    y = T_BAR + 26
    lh = 23
    for kind, s in LINES[:visible]:
        draw_mono(d, 22, y, s, T_COLOR[kind], cjk_bold=(kind in ("title", "save")))
        y += lh
    # 光标
    if cursor_on and visible < len(LINES) + 1:
        d.rectangle([22, y + 1, 22 + 9, y + FS + 1], fill=(88, 166, 255))
    return im


def build_terminal():
    frames = []
    for i in range(1, len(LINES) + 1):
        frames.append(render_terminal(i, cursor_on=(i % 2 == 0)))
    for j in range(5):  # 末帧停留
        frames.append(render_terminal(len(LINES), cursor_on=(j % 2 == 0)))
    gif_path = os.path.join(OUT, "pipeline-live.gif")
    p = [f.convert("P", palette=Image.ADAPTIVE, colors=32) for f in frames]
    p[0].save(
        gif_path,
        save_all=True,
        append_images=p[1:],
        duration=210,
        loop=0,
        optimize=True,
        disposal=2,
    )
    png_path = os.path.join(OUT, "terminal-live.png")
    frames[-1].save(png_path)
    return gif_path, png_path


CHROME = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def rasterize(svg_name: str, out_name: str, w: int, h: int, scale: int = 2) -> bool:
    """用本机 Chromium 内核把 SVG 渲染为 2x PNG（字体嵌入像素，跨环境显示一致）。"""
    import subprocess

    exe = next((p for p in CHROME if os.path.exists(p)), None)
    if not exe:
        print(f"  (跳过 {out_name}：未找到 Chrome/Edge)")
        return False
    out = os.path.join(OUT, out_name)
    url = "file:///" + os.path.join(OUT, svg_name).replace("\\", "/")
    cmd = [
        exe, "--headless=new", "--disable-gpu", "--hide-scrollbars",
        f"--force-device-scale-factor={scale}", f"--window-size={w},{h}",
        "--default-background-color=FFFFFFFF", f"--screenshot={out}", url,
    ]
    try:
        subprocess.run(cmd, capture_output=True, timeout=90, check=False)
    except Exception as e:  # noqa: BLE001
        print(f"  (渲染 {out_name} 失败：{e})")
        return False
    return os.path.exists(out)


def main():
    with open(os.path.join(OUT, "hero.svg"), "w", encoding="utf-8") as f:
        f.write(build_hero())
    with open(os.path.join(OUT, "architecture.svg"), "w", encoding="utf-8") as f:
        f.write(build_architecture())
    gif, png = build_terminal()
    rasterize("hero.svg", "hero.png", 1200, 300)
    rasterize("architecture.svg", "architecture.png", 1240, 790)
    for p in ("hero.png", "architecture.png", "hero.svg", "architecture.svg"):
        fp = os.path.join(OUT, p)
        if os.path.exists(fp):
            print(f"  {p:22s} {os.path.getsize(fp) / 1024:7.1f} KB")
    print(f"  pipeline-live.gif      {os.path.getsize(gif) / 1024:7.1f} KB")
    print(f"  terminal-live.png      {os.path.getsize(png) / 1024:7.1f} KB")


if __name__ == "__main__":
    main()
