#!/usr/bin/env python3
"""block-beta 草图的生成与检查（source-faithful-slides）。只用 Python 标准库。

    python blockbeta.py build 页.json [-o 页.mmd]        按版面描述生成 block-beta
    python blockbeta.py check 页.mmd ... [--terms 表.md] [--wrap N]
                                                         检查已有的 block-beta（手写的也可以）
    python blockbeta.py text 页.mmd ...                  列出上屏文字，供同步检查

版面描述的格式与各条限制见 references/block-beta.md。build、check 发现错误时退出码为 1。
"""
import argparse
import json
import re
import sys
import unicodedata

DEFAULT_WRAP = 40  # 每行显示宽度：汉字算 2，西文、数字算 1；40 约为 20 个汉字
DEFAULT_CLASSES = {  # 小表格的表头与数据格；颜色取视觉规范里的示例角色，可在 classDefs 里覆盖
    "th": "fill:#E8EEF6,stroke:#B8B8B8,color:#1B2A41,font-weight:bold",
    "td": "fill:#FFFFFF,stroke:#D6D6D6,color:#404040",
}
ID_RE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
RESERVED = {"end", "space", "block", "columns", "class", "classdef", "style", "linkstyle", "click", "default"}  # 不分大小写
NO_START = set("，。、：；！？）」』】》,.:;!?)%—～")  # 不放在行首的标点，跟前一段（破折号、波浪号连接前后，两边都不断）
NO_END = set("（「『【《(—～")  # 不放在行尾的标点，跟后一段
BR_RE = re.compile(r"<br\s*/?>", re.I)
ENTITIES = {"#quot;": '"', "#lt;": "<", "#gt;": ">", "#amp;": "&"}
KEYS = {  # 版面描述里四种项各自允许的字段
    "id": {"id", "text", "span", "class", "wrap"},
    "space": {"space"},
    "block": {"block", "columns", "rows", "span", "class"},
    "table": {"table", "header", "rows", "span", "class", "wrap"},
}
TOP_KEYS = {"columns", "wrap", "rows", "edges", "classDefs"}


class SpecError(Exception):
    pass


# ── 文字：宽度、换行、转义 ──

def width(s):
    return sum(2 if unicodedata.east_asian_width(c) in ("W", "F") else 1 for c in s)


def units(s):
    """切成可断行的单元：每个汉字一段，连续的西文、数字（不含空格）一段；返回 (文字, 前面有没有空格)。"""
    out, i, space = [], 0, False
    while i < len(s):
        ch = s[i]
        if ch == " ":
            space, i = True, i + 1
            continue
        if ord(ch) < 128:
            j = i
            while j < len(s) and ord(s[j]) < 128 and s[j] != " ":
                j += 1
            tok, i = s[i:j], j
        else:
            tok, i = ch, i + 1
        if out and not space and (tok[0] in NO_START or out[-1][0][-1] in NO_END):
            out[-1] = (out[-1][0] + tok, out[-1][1])
        else:
            out.append((tok, space))
        space = False
    return out


def wrap(text, limit):
    """按显示宽度在单元之间断行；原文的换行（\\n）照留。在空格处断开时，空格留在上一行末尾，
    还原上屏文字时才分得清原文有没有空格。超长的单个单元不拆，由 check 提醒。"""
    lines = []
    for para in text.split("\n"):
        cur = ""
        for tok, space in units(para):
            add = (" " if space and cur else "") + tok
            if cur and width(cur + add) > limit:
                lines.append(cur + (" " if space else ""))
                cur = tok
            else:
                cur += add
        lines.append(cur)
    return lines


def escape(s):
    return s.replace("&", "#amp;").replace('"', "#quot;").replace("<", "#lt;").replace(">", "#gt;")


def unescape(s):
    for k, v in ENTITIES.items():
        s = s.replace(k, v)
    return re.sub(r"#(\d+);", lambda m: chr(int(m.group(1))), s)


def label(text, limit):
    return '"' + "<br/>".join(escape(x) for x in wrap(text, limit)) + '"'


def screen_text(raw):
    """把标签还原成上屏文字：<br/> 一侧有空格就照留一个空格；两侧都是西文字母或数字（手写的草图）补一个空格；其余直接相接。"""
    parts = [unescape(x) for x in BR_RE.split(raw)]
    out = parts[0]
    for x in parts[1:]:
        if out and x and not out[-1].isspace() and not x[0].isspace() \
                and out[-1].isascii() and out[-1].isalnum() and x[0].isascii() and x[0].isalnum():
            out += " "
        out += x
    return re.sub(r"\s+", " ", out).strip()


def squash(s):
    return re.sub(r"\s+", "", s)


# ── build：版面描述 → block-beta ──

def _int(v, where, what, low=1):
    if isinstance(v, bool) or not isinstance(v, int) or v < low:
        raise SpecError(f"{where}：{what} 要是不小于 {low} 的整数")
    return v


def build(spec):
    if not isinstance(spec, dict):
        raise SpecError("版面描述要是一个 JSON 对象")
    extra = set(spec) - TOP_KEYS
    if extra:
        raise SpecError(f"最外层有不认识的字段：{sorted(extra)}")
    _int(spec.get("columns"), "最外层", "columns")
    limit = _int(spec.get("wrap", DEFAULT_WRAP), "最外层", "wrap", 4)
    cd = spec.get("classDefs", {})
    if not isinstance(cd, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in cd.items()):
        raise SpecError("classDefs 要是「样式名 → 样式文字」的对象")
    classdefs = dict(DEFAULT_CLASSES)
    classdefs.update(cd)
    ids, used, out = set(), {}, ["block-beta"]

    def new_id(i, where):
        if not isinstance(i, str) or not ID_RE.match(i):
            raise SpecError(f"{where}：ID {i!r} 只能用英文字母开头，后接字母、数字或下划线")
        if i.lower() in RESERVED:
            raise SpecError(f"{where}：ID {i} 是 block-beta 的保留字，换一个")
        if i in ids:
            raise SpecError(f"{where}：ID {i} 重复")
        ids.add(i)

    def use(cls, i, where):
        if cls is None:
            return
        if not isinstance(cls, str) or cls not in classdefs:
            raise SpecError(f"{where}：class {cls!r} 在 classDefs 里没有定义")
        used.setdefault(cls, []).append(i)

    def text_of(v, where, what):
        if isinstance(v, bool) or not isinstance(v, (str, int, float)) or not str(v).strip():
            raise SpecError(f"{where}：{what}要是非空的文字或数字")
        return str(v)

    def kind_of(item, where):
        if not isinstance(item, dict):
            raise SpecError(f"{where}：每项要是对象")
        kinds = [k for k in KEYS if k in item]
        if len(kinds) != 1:
            raise SpecError(f"{where}：每项要有且只有 id、space、block、table 之一（现在是 {kinds or '都没有'}）")
        extra = set(item) - KEYS[kinds[0]]
        if extra:
            raise SpecError(f"{where}：{kinds[0]} 项不认识的字段 {sorted(extra)}")
        return kinds[0]

    def span_of(item, nested, where):
        n = _int(item.get("span", 1), where, "span")
        if nested and n > 1:
            raise SpecError(f"{where}：嵌套块里不用跨列（span {n}）——会把整个嵌套块的每一列撑到跨列单元的宽度")
        return n

    def level(rows, cols, depth, where):
        pad = "  " * (depth + 1)
        out.append(f"{pad}columns {cols}")
        if not isinstance(rows, list) or not rows:
            raise SpecError(f"{where}：rows 要是非空列表")
        for r, row in enumerate(rows, 1):
            here = f"{where} 第 {r} 行"
            if not isinstance(row, list) or not row:
                raise SpecError(f"{here}：每行要是非空列表")
            line, total = [], 0
            for k, item in enumerate(row, 1):
                at = f"{here} 第 {k} 项"
                kind = kind_of(item, at)
                if kind == "space":
                    n = _int(item["space"], at, "space")
                    line.append("space" if n == 1 else f"space:{n}")  # 嵌套块里的 space:N 实测不撑宽，照写
                    total += n
                elif kind in ("block", "table"):
                    n = span_of(item, depth > 0, at)
                    if line:
                        out.append(pad + " ".join(line))
                        line = []
                    bid = item[kind]
                    new_id(bid, at)
                    use(item.get("class"), bid, at)
                    out.append(f"{pad}block:{bid}" + (f":{n}" if n > 1 else ""))
                    if kind == "block":
                        level(item.get("rows"), _int(item.get("columns"), at, "columns"), depth + 1, f"块 {bid}")
                    else:
                        table(item, bid, depth + 1, at)
                    out.append(f"{pad}end")
                    total += n
                else:
                    n = span_of(item, depth > 0, at)
                    new_id(item["id"], at)
                    t = text_of(item.get("text"), at, f"块 {item['id']} 的 text ")
                    use(item.get("class"), item["id"], at)
                    lim = _int(item.get("wrap", limit), at, "wrap", 4)
                    line.append(f"{item['id']}[{label(t, lim)}]" + (f":{n}" if n > 1 else ""))
                    total += n
            if line:
                out.append(pad + " ".join(line))
            if total != cols:
                raise SpecError(f"{here}：各项宽度加起来是 {total}，应等于 columns {cols}（不足用 space 补齐）")

    def table(item, tid, depth, where):
        head, rows = item.get("header"), item.get("rows")
        if not isinstance(head, list) or not head or not isinstance(rows, list) or not rows:
            raise SpecError(f"{where}：小表格要有非空的 header 与 rows")
        pad, lim = "  " * (depth + 1), _int(item.get("wrap", limit), where, "wrap", 4)
        out.append(f"{pad}columns {len(head)}")
        for i, row in enumerate([head] + rows):
            if not isinstance(row, list) or len(row) != len(head):
                raise SpecError(f"{where}：表格第 {i} 行的格数与表头不同")
            cells = []
            for j, v in enumerate(row, 1):
                cid = f"{tid}_h{j}" if i == 0 else f"{tid}_r{i}c{j}"
                new_id(cid, where)
                used.setdefault("th" if i == 0 else "td", []).append(cid)
                cells.append(f"{cid}[{label(text_of(v, where, '表格的格'), lim)}]")
            out.append(pad + " ".join(cells))

    level(spec.get("rows"), spec["columns"], 0, "最外层")
    edges = spec.get("edges", [])
    if not isinstance(edges, list):
        raise SpecError("edges 要是列表")
    for e in edges:
        if not isinstance(e, list) or len(e) not in (2, 3):
            raise SpecError(f"箭头 {e!r} 要写成 [起点, 终点] 或 [起点, 终点, 文字]")
        for end in e[:2]:
            if not isinstance(end, str) or end not in ids:
                raise SpecError(f"箭头 {e!r} 的端点 {end!r} 没有定义")
        if len(e) == 3:
            out.append(f"  {e[0]} -- {label(text_of(e[2], f'箭头 {e!r}', '箭头文字'), limit)} --> {e[1]}")
        else:
            out.append(f"  {e[0]} --> {e[1]}")
    for cls, members in used.items():
        out.append(f"  class {','.join(members)} {cls}")
    for cls in used:
        out.append(f"  classDef {cls} {classdefs[cls]}")
    return "\n".join(out) + "\n"


# ── check / text：读已有的 block-beta ──

SKIP_WORDS = ("classDef", "class", "style", "linkStyle", "click", "accTitle", "accDescr")
ARROW = r'--\s*"(?P<al>[^"]*)"\s*-->|<-->|-->|---|==>|-\.->'
ARROW_NEXT = re.compile(r"\s*(?:" + ARROW.replace("?P<al>", "") + ")")
TOKEN = re.compile(r"""
    (?P<arrow>""" + ARROW + r""")
  | (?P<columns>columns\s+(?P<cols>\d+|auto)(?=\s|$))
  | (?P<end>end(?=\s|$))
  | (?P<space>space(?::(?P<sn>\d+))?(?=\s|$))
  | (?P<block>block(?::(?P<bid>[A-Za-z_][\w-]*))?(?::(?P<bn>\d+))?(?=\s|$))
  | (?P<node>(?P<nid>[A-Za-z_][\w-]*)
        (?P<shape>[\[({>]+(?:"(?P<q>[^"]*)"|(?P<u>[^\])}"]*))[\])}]*)?
        (?::(?P<nn>\d+))?)
""", re.X)


def read_terms(path):
    """读「内部代号 → 读者用语」对照表：第一格是「内部代号」的 Markdown 表格。"""
    terms, on = [], False
    with open(path, encoding="utf-8") as f:
        for ln in f:
            s = ln.strip()
            if not s.startswith("|"):
                on = False
                continue
            cells = [c.strip().strip("`").strip() for c in s.strip("|").split("|")]
            if cells and cells[0] == "内部代号":
                on = True
                continue
            if on and cells and cells[0] and not set(cells[0]) <= set("-: "):
                terms.append((cells[0], cells[1] if len(cells) > 1 else ""))
    return terms


def parse(path):
    """返回 (上屏文字列表 [(名称, 原始标签, 是否带引号)], 错误, 提醒)。
    名称是块 ID，或「箭头 a→b」；没有文字的块，原始标签就是它的 ID（Mermaid 会把 ID 当文字上屏）。"""
    errors, warns, nodes, seen = [], [], [], set()
    stack = [{"id": "最外层", "cols": None, "fill": 0, "depth": 0}]
    with open(path, encoding="utf-8") as f:
        text = f.read()
    header = False
    for no, ln in enumerate(text.splitlines(), 1):
        s = ln.strip()
        if not s or s.startswith("%%"):
            continue
        if not header:
            header = True
            if not s.startswith("block"):
                errors.append(f"第 {no} 行：第一行应为 block-beta")
            continue
        if s.split()[0] in SKIP_WORDS:
            continue
        pos, after_arrow, src = 0, None, None
        while pos < len(s):
            if s[pos].isspace():
                pos += 1
                continue
            if s.startswith("%%", pos):
                warns.append(f"第 {no} 行：行尾注释之后未检查")
                break
            m = TOKEN.match(s, pos)
            if not m:
                warns.append(f"第 {no} 行：看不懂的写法，从「{s[pos:pos + 20]}」起未检查")
                break
            pos = m.end()
            lv = stack[-1]

            def place(w, what, is_space=False):
                if lv["depth"] > 0 and w > 1 and not is_space:
                    errors.append(f"第 {no} 行：{what} 在嵌套块 {lv['id']} 里跨 {w} 列——嵌套块里不用跨列")
                if lv["cols"]:
                    if lv["fill"] % lv["cols"] + w > lv["cols"]:
                        errors.append(f"第 {no} 行：{what} 宽 {w}，放不进 {lv['id']} 当前行剩下的 "
                                      f"{lv['cols'] - lv['fill'] % lv['cols']} 列，会错位到下一行")
                lv["fill"] += w

            if m.group("arrow"):
                after_arrow = m.group("al")  # 箭头文字（没有文字时为 None）
                if after_arrow is None:
                    after_arrow = ""
                continue
            if m.group("columns"):
                c = m.group("cols")
                lv["cols"] = int(c) if c.isdigit() else None
            elif m.group("end"):
                if len(stack) == 1:
                    errors.append(f"第 {no} 行：多出的 end")
                else:
                    done = stack.pop()
                    if done["cols"] and done["fill"] % done["cols"]:
                        warns.append(f"块 {done['id']} 的最后一行没有填满 {done['cols']} 列")
            elif m.group("space"):
                place(int(m.group("sn") or 1), "space", True)
            elif m.group("block"):
                w = int(m.group("bn") or 1)
                bid = m.group("bid") or f"（第 {no} 行的匿名块）"
                if m.group("bid"):
                    if bid.lower() in RESERVED:
                        errors.append(f"第 {no} 行：块 ID {bid} 是保留字")
                    if bid in seen:
                        errors.append(f"第 {no} 行：块 {bid} 重复定义——全页 ID 不能重复")
                    seen.add(bid)
                place(w, f"块 {bid}")
                stack.append({"id": bid, "cols": None, "fill": 0, "depth": lv["depth"] + 1})
            else:
                nid = m.group("nid")
                has_shape = m.group("shape") is not None
                in_edge = after_arrow is not None or bool(ARROW_NEXT.match(s, pos))
                if after_arrow is not None:
                    if after_arrow:
                        nodes.append((f"箭头 {src}→{nid}", after_arrow, True))
                    after_arrow = None
                src = nid
                if nid.lower() in RESERVED:
                    errors.append(f"第 {no} 行：块 ID {nid} 是 block-beta 的保留字")
                if nid in seen:
                    if has_shape or not in_edge:  # 箭头里不带文字的引用照常；其余都是重复定义
                        errors.append(f"第 {no} 行：块 {nid} 重复定义——全页 ID 不能重复")
                        if has_shape:  # 后一个标签也列出、也查代号
                            q = m.group("q")
                            nodes.append((nid, q if q is not None else (m.group("u") or ""), q is not None))
                    continue
                if in_edge and not has_shape:
                    errors.append(f"第 {no} 行：箭头引用了还没定义的块 {nid}——箭头要写在所有块定义之后")
                    continue
                seen.add(nid)
                if in_edge:
                    warns.append(f"第 {no} 行：块 {nid} 是在箭头里新定义的，会占一个位置")
                q, u = m.group("q"), m.group("u")
                if not has_shape:
                    warns.append(f"第 {no} 行：块 {nid} 没有文字，会把 ID 当文字上屏")
                    nodes.append((nid, nid, False))
                elif q is None:
                    errors.append(f"第 {no} 行：块 {nid} 的上屏文字没有写在双引号里")
                    nodes.append((nid, u or "", False))
                else:
                    nodes.append((nid, q, True))
                place(int(m.group("nn") or 1), f"块 {nid}")
        if after_arrow is not None:
            errors.append(f"第 {no} 行：箭头后面没有终点")
    if len(stack) > 1:
        errors.append(f"块 {stack[-1]['id']} 没有 end")
    top = stack[0]
    if top["cols"] and top["fill"] % top["cols"]:
        warns.append(f"最外层的最后一行没有填满 {top['cols']} 列")
    return nodes, errors, warns


def check(paths, terms_path, limit):
    terms = read_terms(terms_path) if terms_path else []
    if terms_path and not terms:
        print(f"{terms_path}：没有找到第一格是「内部代号」的对照表")
        return 1
    bad = 0
    for path in paths:
        nodes, errors, warns = parse(path)
        for name, raw, _q in nodes:
            for part in BR_RE.split(raw):
                if width(unescape(part).strip()) > limit:
                    warns.append(f"{name} 有一行宽 {width(unescape(part).strip())}，超过 {limit}：{unescape(part)[:30]}")
            shown = screen_text(raw)
            for code, reader in terms:
                if re.search(r"(?<![A-Za-z0-9])" + re.escape(code) + r"(?![A-Za-z0-9])", shown) \
                        and not (reader and squash(reader) in squash(shown)):
                    errors.append(f"{name} 的上屏文字有内部代号「{code}」（读者用语：{reader or '未填'}）：{shown[:40]}")
        print(f"{path}：{'错误 ' + str(len(errors)) + ' 条' if errors else '没有错误'}，提醒 {len(warns)} 条")
        for x in errors:
            print(f"  [错误] {x}")
        for x in warns:
            print(f"  [提醒] {x}")
        bad += bool(errors)
    return 1 if bad else 0


def text(paths):
    for path in paths:
        print(f"## {path}")
        for name, raw, _q in parse(path)[0]:
            print(f"{name}\t{screen_text(raw)}")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(description="block-beta 草图的生成与检查")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="按版面描述（JSON）生成 block-beta")
    b.add_argument("spec")
    b.add_argument("-o", "--out")
    c = sub.add_parser("check", help="检查已有的 block-beta")
    c.add_argument("mmd", nargs="+")
    c.add_argument("--terms", help="含「内部代号 → 读者用语」对照表的 Markdown 文件")
    c.add_argument("--wrap", type=int, default=DEFAULT_WRAP, help="每行显示宽度上限（汉字算 2）")
    t = sub.add_parser("text", help="列出上屏文字")
    t.add_argument("mmd", nargs="+")
    a = ap.parse_args(argv)
    if a.cmd == "build":
        try:
            with open(a.spec, encoding="utf-8") as f:
                result = build(json.load(f))
        except (SpecError, json.JSONDecodeError) as e:
            print(f"{a.spec}：{e}")
            return 1
        if a.out:
            with open(a.out, "w", encoding="utf-8", newline="\n") as f:
                f.write(result)
            print(f"写入 {a.out}")
        else:
            sys.stdout.write(result)
        return 0
    if a.cmd == "check":
        return check(a.mmd, a.terms, a.wrap)
    return text(a.mmd)


if __name__ == "__main__":
    sys.exit(main())
