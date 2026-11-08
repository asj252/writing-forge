#!/usr/bin/env python3
"""顶会论文提交预检、只读保护清单快照与报告校验脚本（仅依赖 Python 标准库）。

功能：
1. 双盲匿名与工作区路径泄漏扫描（POSIX/Windows 用户目录绝对路径、本地 URI、邮箱、第一人称自引、未脱敏致谢章节等）。
2. 顶会必交章节标题与复现要素核查（识别代码围栏外的 Markdown / LaTeX / Typst 标题，支持 LaTeX 尾随 \\label 与注释，避免将正文普通词汇或代码块内示例误判为正式合规章节）。
3. 稿件表格数字提取与 JSON 汇总原件（summary_*.json）交叉核对提示。
4. 送审输入路径保护清单收集与 SHA-256 快照比对（支持工作目录外 JSON/CSV/TeX 原件、中文路径与含空格路径，使用 os.path.lexists 拦截既有文件与悬空符号链接）。
5. 审查报告完整性与末行独立判定 fail-closed 解析与自测（--selftest）：
   - 严格匹配末行『**总体判定：无阻断**』或『**总体判定：有阻断**』；
   - 对『无阻断』与『有阻断』统一强制检查必交章节实质内容与表格结构（拦截以“未执行数值对账”“略”敷衍的未完成报告，同时保留记载待审对象自身缺陷的有效负面报告）；
   - 对 auditor 报告按稿件声明的展示精度（Decimal 指数，含科学计数法）精确核算末位舍入容差（±0.5 × 10^exp），规范化状态列（拦截 `PASS（已核对）` 等绕过尝试），校验声称执行的脚本路径真实存在；
   - 对 arr 报告统一强制校验宣称映射表、混淆矩阵表、文献定位内容及全部四项顶会评分（Soundness / Excitement / Overall / Confidence）。
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, InvalidOperation
import hashlib
import io
import json
import os
import pathlib
import re
import sys
import unittest
from typing import Any

sys.dont_write_bytecode = True

EXACT_VERDICTS: dict[str, str] = {
    "**总体判定：无阻断**": "无阻断",
    "**总体判定：有阻断**": "有阻断",
}
LOOSE_VERDICT_TOKEN_RE = re.compile(r"总体判定\s*[：:]\s*(无阻断|有阻断)")
INLINE_CODE_RE = re.compile(r"`[^`]+`")

REQUIRED_SECTIONS_BY_TYPE: dict[str, tuple[str, ...]] = {
    "arr": ("一、", "二、", "三、", "四、", "五、"),
    "auditor": ("一、", "二、", "三、", "四、"),
    "any": (),
}

# 审查进程/沙盒/鉴权自身崩溃标记（在任何判定下均拒绝验收，但忽略行内反引号引用的规则说明）
CLI_CRASH_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)failed\s+to\s+spawn\s+code-mode\s+host"),
    re.compile(r"(?i)bubblewrap\s+is\s+unavailable"),
    re.compile(r"(?i)provided\s+authentication\s+token\s+is\s+expired|token_expired"),
    re.compile(r"(?i)your\s+access\s+token\s+could\s+not\s+be\s+refreshed"),
    re.compile(r"^\[ERROR\]"),
    re.compile(r"^Traceback \(most recent call last\):"),
)

# 指向待审对象/被测实现自身缺陷的前缀（避免将『待审解析器无法读取含空值的 CSV』误判为审查未执行）
TARGET_DEFECT_SUBJECT_RE = re.compile(
    r"(?:待审|被审|被测|所审|目标|作者的?|文中的?|稿件中的?|现有的?)?"
    r"(?:解析器|脚本|代码|程序|函数|模块|实现|系统|模型|算法|方法|流水线|接口|工具|正则|校验器)\s*$"
    r"|\[(?:Blocker|Major|Minor|Question)[^\]]*\]",
    re.IGNORECASE,
)

# 审查者自身未读取待审材料或未执行脚本对账的免责/跳过/计划性标记（在任何判定下均拒绝未完成的敷衍报告）
AUDITOR_UNEXECUTED_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:审查者?|审计者?|本次审查|本次审计|本报告|我|当前环境|由于权限|因权限)[^\n。；;]{0,12}(?:无法|未能|不能|没能)\s*(?:读取|访问|打开|加载|获取|解析|找到|查看|检视)"),
    re.compile(r"^(?:尚)?(?:无法|未能|不能|没能)\s*(?:读取|访问|打开|加载|获取|解析|找到)\s*(?:待审|原始|实验|汇总)?\s*(?:稿件|实验数据|汇总|JSON|CSV|原件|文件|工作区|知识库)"),
    re.compile(r"(?:待审稿件|实验数据|原始\s*JSON|汇总\s*JSON|JSON\s*原件|CSV\s*原件|工作区文件)[^\n，。；;]{0,10}(?:无法|未能|不能|不可)\s*(?:读取|访问|打开|加载|获取)"),
    re.compile(r"(?:找不到|缺失|缺少|未提供|未找到)\s*(?:待审|原始|实验|汇总)\s*(?:稿件|实验数据|汇总|JSON|CSV|原件)"),
    re.compile(r"(?:存在)?送审材料阻断|(?:目标|待审|指定|送审)(?:材料|论文|稿件|文件|卡片|综述|主题)[^\n，。；;]{0,16}(?:不存在|缺失|未找到|找不到|为空)"),
    re.compile(r"(?:无法|未能|不能)\s*(?:完成|开展|进行|执行)[^\n，。；;]{0,8}实质(?:性)?(?:审查|审计|核对|评估|审稿)"),
    re.compile(
        r"(?:尚未|未曾|未能|没有|未)\s*(?:运行|执行|完成|开展|进行|启动)(?!\s*(?:真实模型|子代理))[^\n。；;]*?"
        r"(?:对账|核对|复算|预检|数值检查|本次审查|本次审计|实质审查|实质审计)"
    ),
    re.compile(r"未运行任何(?:对账|核对|复算|预检|检查)(?:命令|脚本)?"),
    re.compile(r"(?:本次|当前)?(?:审查|审计|对账|核对|预检)\s*(?:未完成|尚未完成|未实际完成|未执行|尚未执行|中断|失败|无法进行|未能进行)"),
    re.compile(r"(?:仅作|只作|仅进行|只进行|仅限)\s*静态(?:阅读|审阅|检查|浏览|分析)"),
    re.compile(r"(?:后续|稍后|日后|另行|留待)\s*(?:补交|补充|补跑|补做|再跑|再执行|执行对账|复算)"),
    re.compile(r"(?:对账|复算|核对|脚本|命令|差值|矩阵)[^\n。；;]{0,16}(?:后续补交|待补交|待补|未跑|未执行|未运行|未完成|从略|省略|跳过)"),
    re.compile(r"(?:拟用|拟采用|拟执行|拟运行|计划使用|计划运行|计划执行|准备使用|准备运行|待使用|待运行)\s*(?:工具|命令|脚本)?"),
    re.compile(
        r"(?i)\b(?:cannot|could\s+not|unable\s+to|failed\s+to|did\s+not|have\s+not|has\s+not)\s+"
        r"(?:read|access|open|load|find|locate|inspect|run|execute|perform|verify|reconcile|complete|finish|audit|review)\s+"
        r"(?:the\s+)?(?:manuscript|paper|raw\s+json|summary[_\w.]*|csv|data|workspace|reconciliation|audit|review)\b"
    ),
    re.compile(
        r"(?i)\b(?:numerical\s+reconciliation|reconciliation\s+check|audit|review|verification)\s+"
        r"(?:was\s+not|is\s+not|has\s+not\s+been)\s+(?:yet\s+)?(?:executed|run|performed|reconciled|verified|completed|finished)\b"
    ),
    re.compile(
        r"(?i)\b(?:manuscript|paper|raw\s+json|summary[_\w.]*|experimental\s+data|workspace)\s+"
        r"(?:is|are|was|were)\s+(?:not\s+)?(?:inaccessible|unreadable|unavailable|missing|not\s+found|not\s+accessible|not\s+readable)\b"
    ),
    re.compile(
        r"(?i)\b(?:no\s+(?:reconciliation|verification|audit|precheck|check)\s+(?:command|script|step|check)s?\s+(?:was|were)\s+(?:run|executed|performed))\b"
    ),
    re.compile(
        r"(?i)\b(?:audit|review|reconciliation|verification|check)\s+(?:is\s+|was\s+)?(?:incomplete|unfinished|not\s+completed|not\s+performed|skipped|aborted|pending)\b"
    ),
    re.compile(
        r"(?i)\b(?:static\s+reading\s+only|deferred\s+to\s+later|to\s+be\s+(?:reconciled|executed|run|supplied|added)\s+later)\b"
    ),
)

STUB_SECTION_BODY_RE = re.compile(
    r"^\s*(?:略|从略|同上|待补|暂无|无|见上|如上|省略|跳过|TBD|TODO|N/?A|none|skipped)[。.;；!！，,\s]*$",
    re.IGNORECASE,
)

BLOCKER_TAG_RE = re.compile(r"\[Blocker(?:\s*阻断)?\]", re.IGNORECASE)
CLAUSE_SEP_RE = re.compile(r"[；;。！!？?|\n，,]")
NEGATED_PREFIX_RE = re.compile(
    r"(?:(?:无|未发现|未见|没有|不存在|零\s*(?:项|个|处)?)|(?<![\d.])0(?![\d.])\s*(?:项|个|处)?|(?<![A-Za-z])(?:no|zero|none|without)\b)"
    r"\s*(?:\*\*|`)*\s*$",
    re.IGNORECASE,
)
NEGATED_SUFFIX_RE = re.compile(
    r"^\s*(?:\*\*|`)*\s*(?:[：:]\s*)?(?:无|(?<![\d.])0(?![\d.])\s*(?:项|个|处)?|零\s*(?:项|个|处)?|None\b|N/A\b)(?:\s*$|\s*[。；;，,|])",
    re.IGNORECASE,
)
BLOCKER_COUNT_RE = re.compile(r"(?<![未无\u7121])(?:发现|共|有|存在)\s*(?:\*\*|`)*\s*[1-9]\d*\s*项[^\n。；;]*?(?:阻断|\[Blocker)")

PASS_FAIL_LEGEND_RE = re.compile(r"\bPASS\s*(?:[/|]|或|or)\s*(?:FAIL|MISMATCH)\b", re.IGNORECASE)
AUDITOR_STATUS_TOKEN_RE = re.compile(r"\b(?:MISMATCH|FAIL)\b")
AUDITOR_TEXT_MISMATCH_RE = re.compile(r"(?:不一致|不吻合)")
MISMATCH_NEGATED_PREFIX_RE = re.compile(
    r"(?:无|未发现|未见|没有|不存在|(?:(?<![\d.])0(?![\d.])|零)\s*(?:处|项|个)?)\s*(?:任何|数值|数据|结果|指标)?\s*$"
)

ARR_SEC1_POSITIVE_RE = re.compile(r"(?:宣称|闭合|核对|映射|证据|过度宣称|缺口|claim)", re.IGNORECASE)
ARR_SEC2_POSITIVE_RE = re.compile(r"(?:混淆|替代解释|消融|CoT|API|ROC-AUC|confound|ablation|不适用)", re.IGNORECASE)
ARR_SEC3_POSITIVE_RE = re.compile(r"(?:lit_kb|kb|知识库|竞品|基线|文献|baseline|Related\s+Work)", re.IGNORECASE)
ARR_TABLE_SEP_RE = re.compile(r"^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?\s*$")
ARR_SCORE_EXTRACT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "Soundness",
        re.compile(r"(?i)\bSoundness\b[^\n\d+-]{0,25}([+-]?\d+(?:\.\d+)?)(?:\s*/\s*([+-]?\d+(?:\.\d+)?))?"),
    ),
    (
        "Excitement",
        re.compile(r"(?i)\bExcitement\b[^\n\d+-]{0,25}([+-]?\d+(?:\.\d+)?)(?:\s*/\s*([+-]?\d+(?:\.\d+)?))?"),
    ),
    (
        "Overall Assessment",
        re.compile(
            r"(?i)\bOverall(?:\s+Assessment)?\b[^\n\d+-]{0,25}([+-]?\d+(?:\.\d+)?)(?:\s*/\s*([+-]?\d+(?:\.\d+)?))?"
        ),
    ),
    (
        "Reviewer Confidence",
        re.compile(
            r"(?i)\b(?:Reviewer\s+)?Confidence\b[^\n\d+-]{0,25}([+-]?\d+(?:\.\d+)?)(?:\s*/\s*([+-]?\d+(?:\.\d+)?))?"
        ),
    ),
)

AUDITOR_SEC1_CMD_RE = re.compile(
    r"(?:\bpython3?\s+(?:-[A-Za-z]+\s+\S+|\S+\.py\b)|\bbash\s+\S+\.sh\b|submission_precheck\.py\s+\S+)",
    re.IGNORECASE,
)
SCRIPT_INVOCATION_RE = re.compile(
    r"\b(?:python3?|bash|sh)\s+(?:-[A-Za-z]+\s+)*([^\s`'\"|;&><]+\.(?:py|sh))\b",
    re.IGNORECASE,
)
AUDITOR_SEC1_POSITIVE_RE = re.compile(r"(?:一致|吻合|零误差|\bPASS\b)", re.IGNORECASE)
AUDITOR_SEC2_POSITIVE_RE = re.compile(r"(?:符号|公式|退化|边界|认知|图表|自明)", re.IGNORECASE)
AUDITOR_SEC3_POSITIVE_RE = re.compile(r"(?:零泄漏|无泄漏|匿名|合规|\bPASS\b|通过|Limitations)", re.IGNORECASE)
AUDITOR_SEC3_ANY_EVIDENCE_RE = re.compile(r"(?:零泄漏|无泄漏|泄漏|匿名|合规|\bPASS\b|\bFAIL\b|通过|Limitations)", re.IGNORECASE)

NUM_TOKEN_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?(?:e[+-]?\d+)?%?$", re.IGNORECASE)
PAREN_NOTE_RE = re.compile(r"\s*(?:\([^)]*\)|（[^）]*）)\s*")
NORM_PASS_STATUS_RE = re.compile(r"^(?:PASS|一致|零误差|吻合)$", re.IGNORECASE)
NORM_FAIL_STATUS_RE = re.compile(r"^(?:MISMATCH|FAIL|不一致|不吻合)$", re.IGNORECASE)
HEADER_CELL_KEYWORD_RE = re.compile(
    r"(?:稿件|原件|差值|状态|位置|指标|模型|字段|复算|Manuscript|Paper|Source|Raw|Diff|Delta|Status|Metric)",
    re.IGNORECASE,
)

FENCE_OPEN_RE = re.compile(r"^\s*(`{3,}|~{3,})")

LEAK_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "local_abs_path",
        re.compile(r"(?<![\w.:/-])/(?:Users" + r"|home)/[^\s/]+"),
        "疑似 POSIX 本机或云端用户目录路径外泄",
    ),
    (
        "windows_user_path",
        re.compile(r"(?i)(?<![a-z0-9])[a-z]:\\+Users\\+[^\s\\'\"]+"),
        "疑似 Windows 本机用户目录路径外泄",
    ),
    (
        "local_uri_scheme",
        re.compile(r"(?i)\bfi" + r"le://"),
        "疑似本机 URI 链接外泄",
    ),
    (
        "email_address",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}\b"),
        "疑似邮箱地址外泄（双盲审稿违规风险）",
    ),
    (
        "self_identifying_citation",
        re.compile(
            r"(?i)\b(?:in\s+our\s+(?:prior|previous|earlier)\s+work|we\s+previously\s+showed|as\s+we\s+showed\s+in)\b"
        ),
        "疑似第一人称自引措辞（建议改为第三人称客观引用）",
    ),
    (
        "acknowledgments_section",
        re.compile(
            r"(?i)^\s*(?:#+\s*|=+\s*|\\(?:sub)*section\*?\{|\\paragraph\*?\{)\s*(?:acknowledg(?:e)?ments?|致谢)\b"
        ),
        "疑似在双盲审稿稿件中保留了致谢（Acknowledgments）章节标题",
    ),
]

MD_TYPST_HEADING_RE = re.compile(r"^\s*(?:#+\s+(.+?)|=+\s+(.+?))\s*$")
LATEX_HEADING_RE = re.compile(
    r"^\s*\\(?:(?:sub)*section|paragraph)\*?\{([^}]+)\}(?:\s*\\label\{[^}]*\})*\s*(?:%.*)?$"
)

COMPLIANCE_HEADING_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("Limitations（局限性章节标题）", re.compile(r"(?i)\blimitations?\b|局限")),
    (
        "Ethics / Broader Impact（伦理与社会影响章节标题）",
        re.compile(r"(?i)\bethic(?:s|al)?\b|\bbroader\s+impacts?\b|伦理|社会影响"),
    ),
]

REPRO_HEADING_RE = re.compile(
    r"(?i)\breproducib(?:le|ility)\b|\bexperimental\s+setup\b|\bimplementation\s+details\b|可复现|实验设置|实现细节"
)
REPRO_PARAM_MARKERS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\btemperature\b|温度"),
    re.compile(r"(?i)\btop_p\b"),
    re.compile(r"(?i)\bmax_tokens\b|最大生成长度"),
    re.compile(r"(?i)\bseed\b|随机种子"),
    re.compile(r"(?i)\bbootstrap\b|置信区间"),
)


def parse_lines_with_fence_state(lines: list[str]) -> tuple[list[tuple[int, str, bool]], bool]:
    """返回非围栏分隔符行的 (行号, 行内容, 是否在代码围栏内) 列表，以及围栏是否在文末正常闭合。"""
    out: list[tuple[int, str, bool]] = []
    active_fence: str | None = None
    for idx, ln in enumerate(lines, 1):
        m = FENCE_OPEN_RE.match(ln)
        if m:
            marker = m.group(1)
            if active_fence is None:
                active_fence = marker
                continue
            if marker[0] == active_fence[0] and len(marker) >= len(active_fence):
                active_fence = None
                continue
        out.append((idx, ln, active_fence is not None))
    return out, active_fence is None


def iter_outside_fences(lines: list[str]) -> tuple[list[tuple[int, str]], bool]:
    """返回不在代码围栏（``` 或 ~~~）内的 (行号, 行内容) 列表，以及围栏是否在文末正常闭合。"""
    parsed, closed = parse_lines_with_fence_state(lines)
    return [(idx, ln) for idx, ln, in_fence in parsed if not in_fence], closed


def has_active_blocker_on_line(line: str) -> bool:
    """逐处检查单行中的 [Blocker] / [Blocker 阻断] 是否全部被紧邻的否定词或零计数修饰（Fail-closed）。"""
    unwrapped = line.replace("`", "").replace("*", "")
    if BLOCKER_COUNT_RE.search(unwrapped):
        return True
    for m in BLOCKER_TAG_RE.finditer(unwrapped):
        prefix_full = unwrapped[: m.start()]
        clause_parts = CLAUSE_SEP_RE.split(prefix_full)
        clause_prefix = clause_parts[-1] if clause_parts else prefix_full
        suffix_full = unwrapped[m.end() :]
        if NEGATED_PREFIX_RE.search(clause_prefix):
            continue
        if NEGATED_SUFFIX_RE.search(suffix_full):
            continue
        return True
    return False


def has_auditor_mismatch_or_fail(line: str) -> bool:
    """检查审计报告单行是否包含未否定的 MISMATCH / FAIL / 不一致（保留反引号与代码块内的状态词）。"""
    unwrapped = PASS_FAIL_LEGEND_RE.sub("", line.replace("`", "").replace("*", ""))
    for m in AUDITOR_STATUS_TOKEN_RE.finditer(unwrapped):
        clause_prefix = CLAUSE_SEP_RE.split(unwrapped[: m.start()])[-1]
        if NEGATED_PREFIX_RE.search(clause_prefix):
            continue
        return True
    for m in AUDITOR_TEXT_MISMATCH_RE.finditer(unwrapped):
        clause_prefix = CLAUSE_SEP_RE.split(unwrapped[: m.start()])[-1]
        if MISMATCH_NEGATED_PREFIX_RE.search(clause_prefix):
            continue
        return True
    return False


def _clean_numeric_cell(cell: str) -> str:
    """剥离单元格外围的 Markdown/LaTeX 修饰符（`、*、_、$）并归一化 \\% 为 %。"""
    s = cell.strip().replace("\\%", "%")
    while len(s) >= 2 and s[0] in "`*_$ " and s[-1] in "`*_$ ":
        s = s.strip("`*_$ ")
    return s.strip("`*_$ ")


def _normalize_status_cell(cell: str) -> str:
    """规范化矩阵状态列：剥离反引号/星号/美元符及良性括号批注（如『PASS（已核对）』->『PASS』）；
    若括号内夹带 MISMATCH/FAIL/不一致 等矛盾词则拒绝规范化为 PASS。
    """
    s = _clean_numeric_cell(cell)
    for pm in PAREN_NOTE_RE.finditer(s):
        note_txt = pm.group(0)
        if re.search(r"(?:MISMATCH|FAIL|不一致|不吻合|阻断)", note_txt, re.IGNORECASE):
            return ""
    s = PAREN_NOTE_RE.sub("", s).strip("`*_$ ")
    return s


def _is_table_header_row(cells: list[str], seen_separator: bool = False) -> bool:
    """判断是否为表头行：
    - 一旦越过 Markdown 表格分隔线（|---|---|），后续行一律视为数据行，绝不当作表头跳过；
    - 只要末尾数值列（稿件数值、原件数值、差值）任一列为数字，绝不当作表头跳过；
    - 仅在分隔线之前、数值列均非数字、且包含至少 2 个表头关键词时才识别为表头。
    """
    if seen_separator or not cells:
        return False
    if len(cells) >= 4:
        s_p = _clean_numeric_cell(cells[-4])
        s_s = _clean_numeric_cell(cells[-3])
        s_d = _clean_numeric_cell(cells[-2])
        if NUM_TOKEN_RE.match(s_p) or NUM_TOKEN_RE.match(s_s) or NUM_TOKEN_RE.match(s_d):
            return False
        header_hits = sum(1 for c in cells[-4:] if HEADER_CELL_KEYWORD_RE.search(c))
        if header_hits >= 2:
            return True
    elif all(not NUM_TOKEN_RE.match(_clean_numeric_cell(c)) for c in cells):
        if sum(1 for c in cells if HEADER_CELL_KEYWORD_RE.search(c)) >= 2:
            return True
    return False


def verify_referenced_scripts_exist(sec1_text: str, workdir: pathlib.Path | None) -> tuple[bool, str]:
    """当提供 workdir 时，核验第一节对账命令中声称执行的 .py/.sh 脚本文件真实存在（拦截虚构的 reconcile.py）。"""
    if workdir is None:
        return True, ""
    this_script_dir = pathlib.Path(__file__).resolve().parent
    candidate_bases = [workdir.resolve(), this_script_dir, pathlib.Path.cwd().resolve()]
    for m in SCRIPT_INVOCATION_RE.finditer(sec1_text):
        script_tok = m.group(1).strip("`'\"()[]{}<>.,;:")
        p = pathlib.Path(script_tok)
        if p.is_absolute():
            if not p.is_file():
                return False, f"章节 '一、' 声称执行的对账脚本不存在：{script_tok!r}"
        else:
            found = any((base / p).is_file() or (base / p.name).is_file() for base in candidate_bases)
            if not found:
                return False, f"章节 '一、' 声称执行的对账脚本在工作区中不存在：{script_tok!r}"
    return True, ""


def _collect_ground_truth_decimals(
    workdir: pathlib.Path | None,
    task_md: pathlib.Path | None = None,
) -> list[Decimal]:
    """从工作目录及送审说明引用的所有 .json / .csv 原件中提取全部真实数值（含集合长度与百分数缩放候选），
    用于核验审计报告对账矩阵中的『原件数值』列并非凭空捏造。
    """
    if workdir is None and task_md is None:
        return []
    data_files: set[pathlib.Path] = set()
    if workdir is not None and workdir.is_dir():
        for dirpath, _, filenames in os.walk(workdir.resolve(), followlinks=True):
            for fn in filenames:
                if fn.endswith((".json", ".csv")) and not fn.startswith("."):
                    fp = (pathlib.Path(dirpath) / fn).resolve()
                    if fp.is_file():
                        data_files.add(fp)
    if task_md is not None and task_md.is_file():
        task_text = task_md.read_text(encoding="utf-8", errors="ignore")
        bases = [b for b in (workdir.resolve() if workdir and workdir.is_dir() else None, task_md.resolve().parent) if b]
        for pat in PATH_CANDIDATE_PATTERNS:
            for m in pat.finditer(task_text):
                raw = (m.group(1) if m.lastindex else m.group(0)).strip().strip(PUNCT_STRIP_CHARS).strip()
                raw = re.sub(r"(?:#L\d+(?:-L?\d+)?|:\d+(?::\d+)?)$", "", raw)
                if not raw.endswith((".json", ".csv")):
                    continue
                p = pathlib.Path(raw)
                if p.is_absolute() and p.is_file():
                    data_files.add(p.resolve())
                else:
                    for b in bases:
                        if (b / p).is_file():
                            data_files.add((b / p).resolve())

    values: set[Decimal] = set()

    def _add_dec(d: Decimal) -> None:
        if not d.is_finite():
            return
        values.add(d)
        # 若原件存 0~1 比例而表格按百分数（×100）记录，或反之，同时纳入 ×100 与 /100 候选
        values.add(d * Decimal("100"))
        values.add(d / Decimal("100"))

    def _walk_json(obj: Any) -> None:
        if isinstance(obj, bool) or obj is None:
            return
        if isinstance(obj, (int, float)):
            try:
                _add_dec(Decimal(str(obj)))
            except InvalidOperation:
                pass
            return
        if isinstance(obj, str):
            s = obj.strip().rstrip("%")
            if NUM_TOKEN_RE.match(s):
                try:
                    _add_dec(Decimal(s))
                except InvalidOperation:
                    pass
            return
        if isinstance(obj, list):
            for item in obj:
                _walk_json(item)
            return
        if isinstance(obj, dict):
            for v in obj.values():
                _walk_json(v)

    for fp in sorted(data_files):
        try:
            if fp.suffix == ".json":
                _walk_json(json.loads(fp.read_text(encoding="utf-8", errors="ignore")))
            elif fp.suffix == ".csv":
                csv_text = fp.read_text(encoding="utf-8", errors="ignore")
                rows = [
                    row
                    for row in csv.reader(io.StringIO(csv_text))
                    if any(cell.strip() for cell in row)
                ]
                for row in rows[1:]:
                    for cell in row:
                        for tok in re.split(r"[,;\t|]", cell):
                            t = tok.strip().strip("\"'").rstrip("%")
                            if NUM_TOKEN_RE.match(t):
                                try:
                                    _add_dec(Decimal(t))
                                except InvalidOperation:
                                    pass
        except Exception:
            continue

    return sorted(values)


def _compute_row_tolerance(v_paper: Decimal, v_src: Decimal) -> Decimal:
    """计算对账行容差：
    - 当稿件数值含小数位或负指数（exp_paper < 0）时，容差为 0.5 × 10^exp_paper；
    - 当稿件展示为整数（exp_paper >= 0）但原件为连续小数（exp_src < 0，如稿件 42 vs 原件 41.8）时，容差为 0.5 × 10^exp_paper；
    - 当稿件与原件均为精确整数（如样本量 n=120 vs 119）时，要求零误差（容差为 0）。
    """
    exp_paper = v_paper.as_tuple().exponent
    exp_src = v_src.as_tuple().exponent
    assert isinstance(exp_paper, int) and isinstance(exp_src, int)
    if exp_paper < 0 or exp_src < 0:
        return Decimal("0.5") * (Decimal(10) ** exp_paper)
    return Decimal("0")


def validate_auditor_sec1_matrix(
    sec1_text: str,
    verdict: str = "无阻断",
    ground_truth_decimals: list[Decimal] | None = None,
) -> tuple[bool, str]:
    """按固定尾部列结构（...| 稿件数值 | 原件数值 | 差值 | 状态）逐行校验第四关数值对账矩阵：
    - 除表头（必须在分隔线之前且不含数字）与分隔线外，每一条表格数据行均须接受校验；
    - 对 PASS 与 MISMATCH 行统一检查差值列算术自洽性（含显式正负号方向一致性）；
    - 当提供工作区 JSON/CSV 原件数值集合时，核验每行『原件数值』真实存在于原件数据中。
    """
    if ground_truth_decimals is not None and len(ground_truth_decimals) == 0:
        return (
            False,
            "未在工作目录或送审说明中找到任何可用的 JSON/CSV 实验原件数值，无法对第四关数值对账矩阵执行原件交叉核对",
        )
    valid_data_rows = 0
    valid_pass_rows = 0
    seen_sep = False
    for raw_ln in sec1_text.splitlines():
        ln = raw_ln.strip()
        if "|" not in ln:
            seen_sep = False
            continue
        if ARR_TABLE_SEP_RE.match(ln):
            seen_sep = True
            continue
        if not seen_sep and not ln.startswith("|"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) < 2:
            continue
        if _is_table_header_row(cells, seen_separator=seen_sep):
            continue

        if len(cells) < 4:
            return False, f"数值对账矩阵数据行列数不足（必须包含稿件数值、原件数值、差值与状态四列）：{ln!r}"

        status_norm = _normalize_status_cell(cells[-1])
        is_pass_row = bool(NORM_PASS_STATUS_RE.match(status_norm))
        is_fail_row = bool(NORM_FAIL_STATUS_RE.match(status_norm))

        if not (is_pass_row or is_fail_row):
            return False, f"数值对账矩阵包含未识别或含冲突备注的状态列 {cells[-1]!r}（仅允许 PASS/一致/零误差 或 MISMATCH/FAIL）：{ln!r}"

        if verdict == "无阻断" and is_fail_row:
            return False, f"数值对账矩阵包含失败状态行 ({cells[-1]!r})，不得判为无阻断：{ln!r}"

        s_paper = _clean_numeric_cell(cells[-4])
        s_src = _clean_numeric_cell(cells[-3])
        s_diff = _clean_numeric_cell(cells[-2])

        if not (NUM_TOKEN_RE.match(s_paper) and NUM_TOKEN_RE.match(s_src) and NUM_TOKEN_RE.match(s_diff)):
            return (
                False,
                f"数值对账矩阵数据行缺少差值列或包含无法解析的数值 ({s_paper!r}, {s_src!r}, {s_diff!r})：{ln!r}",
            )

        pct_paper = s_paper.endswith("%")
        pct_src = s_src.endswith("%")
        pct_diff = s_diff.endswith("%")

        try:
            v_paper = Decimal(s_paper.rstrip("%"))
            v_src = Decimal(s_src.rstrip("%"))
            v_diff = Decimal(s_diff.rstrip("%"))
        except InvalidOperation:
            return False, f"数值对账矩阵行十进制解析失败：{ln!r}"

        if not (v_paper.is_finite() and v_src.is_finite() and v_diff.is_finite()):
            return False, f"数值对账矩阵行包含非有限数值：{ln!r}"

        tol = _compute_row_tolerance(v_paper, v_src)
        signed_diff = v_paper - v_src
        actual_diff = abs(signed_diff)

        # 差值列算术与方向自洽性校验（对 PASS 与 MISMATCH 行均生效）
        diff_has_explicit_sign = s_diff.startswith(("+", "-"))
        if pct_paper == pct_src:
            if diff_has_explicit_sign:
                # 若差值列带显式正负号，必须等于 稿件数值 - 原件数值（方向不得颠倒）
                if abs(v_diff - signed_diff) > tol or (
                    v_diff != Decimal("0")
                    and signed_diff != Decimal("0")
                    and (v_diff > Decimal("0")) != (signed_diff > Decimal("0"))
                ):
                    return (
                        False,
                        f"数值对账矩阵行带符号差值列 ({s_diff!r}) 与 (稿件数值 - 原件数值 = {signed_diff}) 方向或数值不自洽：{ln!r}",
                    )
            else:
                if abs(v_diff - actual_diff) > tol:
                    return (
                        False,
                        f"数值对账矩阵行差值列 ({s_diff!r}) 与 |稿件数值 - 原件数值| ({actual_diff}) 算术不自洽（容差 {tol}）：{ln!r}",
                    )

        # 若已要求核验工作目录/送审说明原件（ground_truth_decimals is not None），核验 v_src 真实存在于原件 JSON/CSV 中
        if ground_truth_decimals is not None:
            src_exp = v_src.as_tuple().exponent
            src_tol = Decimal("0.5") * (Decimal(10) ** src_exp) if isinstance(src_exp, int) and src_exp < 0 else tol
            match_tol = max(tol, src_tol)
            if not any(abs(v_src - gt) <= match_tol for gt in ground_truth_decimals):
                return (
                    False,
                    f"数值对账矩阵行的原件数值 ({s_src!r}) 在工作区 JSON/CSV 原件中未找到匹配项（拦截虚构对账数据）：{ln!r}",
                )

        valid_data_rows += 1

        if is_pass_row:
            if pct_paper != pct_src:
                return False, f"数值对账矩阵 PASS 行的百分号单位不一致 ({s_paper!r} vs {s_src!r})：{ln!r}"
            if pct_paper != pct_diff and v_diff != Decimal("0"):
                return False, f"数值对账矩阵 PASS 行差值列的百分号单位不一致 ({s_paper!r} vs {s_diff!r})：{ln!r}"
            if actual_diff > tol:
                return (
                    False,
                    f"数值对账矩阵行存在超过稿件展示精度舍入容差的差值 (|{v_paper} - {v_src}| = {actual_diff} > 容差 {tol}) 却标为 PASS/一致：{ln!r}",
                )
            if abs(v_diff) > tol:
                return (
                    False,
                    f"数值对账矩阵 PASS 行差值列 ({v_diff}) 超出零误差容差 ({tol})：{ln!r}",
                )
            valid_pass_rows += 1
        else:
            # MISMATCH / FAIL 行必须确实存在数值超差或百分号单位不一致
            if pct_paper == pct_src and actual_diff <= tol:
                return (
                    False,
                    f"数值对账矩阵行差值 (|{v_paper} - {v_src}| = {actual_diff} <= 容差 {tol}) 未超差却标为 MISMATCH/FAIL：{ln!r}",
                )

    if valid_data_rows == 0 or (verdict == "无阻断" and valid_pass_rows == 0):
        return False, "必交章节 '一、' 缺少包含稿件数值、原件数值、差值与状态的逐格对账矩阵数据行"
    return True, ""


def _has_markdown_data_row(section_text: str) -> bool:
    """核验章节包含完整的 Markdown 表格：必须具有表头行、分隔线（|---|---|）以及分隔线后至少 1 行非空实质数据行。"""
    seen_header_before_sep = False
    seen_sep = False
    data_rows_after_sep = 0
    for raw_ln in section_text.splitlines():
        ln = raw_ln.strip()
        if "|" not in ln:
            if seen_sep and data_rows_after_sep > 0:
                return True
            seen_header_before_sep = False
            seen_sep = False
            continue
        if ARR_TABLE_SEP_RE.match(ln):
            if seen_header_before_sep:
                seen_sep = True
            continue
        cells = [c.strip() for c in ln.strip("|").split("|") if c.strip()]
        if len(cells) >= 3:
            if not seen_sep:
                seen_header_before_sep = True
            else:
                data_rows_after_sep += 1
                return True
    return False


def _validate_arr_scores(sec5_text: str) -> tuple[bool, str]:
    """核验 ARR 第五节包含四项必交评分，且分值严格在 [1, 5] 闭区间内（若有分母则必须为 5）。"""
    for score_name, score_pat in ARR_SCORE_EXTRACT_PATTERNS:
        m = score_pat.search(sec5_text)
        if not m:
            return False, f"ARR 审查报告第五节缺少必交评分项：{score_name} (1-5)"
        try:
            val = Decimal(m.group(1))
            den = Decimal(m.group(2)) if m.group(2) is not None else Decimal("5")
        except InvalidOperation:
            return False, f"ARR 审查报告第五节评分项无法解析：{score_name}"
        if not (Decimal("1") <= val <= Decimal("5")) or den != Decimal("5"):
            return (
                False,
                f"ARR 审查报告第五节评分项 {score_name} 越界或分母异常（实得 {m.group(0)!r}，要求 1~5 分制）",
            )
    return True, ""


def extract_headings(lines: list[str]) -> list[str]:
    """提取代码围栏外的 Markdown / Typst / LaTeX 章节标题文本（支持 LaTeX 尾随 \\label 与 % 注释）。"""
    headings: list[str] = []
    outside, _ = iter_outside_fences(lines)
    for _, ln in outside:
        m_md = MD_TYPST_HEADING_RE.match(ln)
        if m_md:
            title = (m_md.group(1) or m_md.group(2) or "").strip().rstrip("#").strip()
            if title:
                headings.append(title)
            continue
        m_tex = LATEX_HEADING_RE.match(ln)
        if m_tex:
            title = m_tex.group(1).strip()
            if title:
                headings.append(title)
    return headings


def _validate_required_sections(
    body_items: list[tuple[str, bool]],
    required_sections: tuple[str, ...],
    report_type: str,
    verdict: str,
    workdir: pathlib.Path | None = None,
    task_md: pathlib.Path | None = None,
) -> tuple[bool, str]:
    """校验必交章节标题均作为代码围栏外的独立标题行按序出现，且每节下（含代码块内）包含实质证据（无阻断与有阻断均须完整）。"""
    if not required_sections:
        return True, ""

    sec_patterns = [
        (
            sec,
            re.compile(rf"^(?:#+\s*|\d+\.\s*|\*\*\s*)?{re.escape(sec)}\S+"),
        )
        for sec in required_sections
    ]

    sec_indices: list[int] = []
    search_start = 0
    for sec, pat in sec_patterns:
        found_idx = -1
        for i in range(search_start, len(body_items)):
            ln, in_fence = body_items[i]
            if in_fence:
                continue
            other_secs = [s for s in required_sections if s != sec and s in ln]
            if pat.match(ln) and not other_secs:
                found_idx = i
                break
        if found_idx == -1:
            return False, f"报告缺少独立的必交章节标题行：{sec!r}"
        sec_indices.append(found_idx)
        search_start = found_idx + 1

    boundaries = sec_indices + [len(body_items)]
    sec_bodies: dict[str, str] = {}
    for idx_pos, sec in enumerate(required_sections):
        start_i = boundaries[idx_pos] + 1
        end_i = boundaries[idx_pos + 1]
        section_body = [
            ln
            for ln, in_fence in body_items[start_i:end_i]
            if in_fence or (not ln.startswith("#") and not any(p.match(ln) for _, p in sec_patterns))
        ]
        if not section_body:
            return False, f"必交章节 {sec!r} 下缺少实质审查正文（空壳章节）"
        joined_body = "\n".join(section_body)
        if sec in ("一、", "二、", "三、", "五、") and STUB_SECTION_BODY_RE.match(joined_body):
            return False, f"必交章节 {sec!r} 仅填写占位词（{joined_body.strip()!r}），缺少实质审查内容"
        sec_bodies[sec] = joined_body

    if report_type == "arr":
        if not (ARR_SEC1_POSITIVE_RE.search(sec_bodies["一、"]) and _has_markdown_data_row(sec_bodies["一、"])):
            return False, "必交章节 '一、' 缺少宣称与证据映射核对表（需含表头、分隔线及至少 1 行实质数据行）"
        if not (ARR_SEC2_POSITIVE_RE.search(sec_bodies["二、"]) and _has_markdown_data_row(sec_bodies["二、"])):
            return False, "必交章节 '二、' 缺少混淆变量与替代解释压力测试矩阵表（需含表头、分隔线及至少 1 行实质数据行）"
        if not ARR_SEC3_POSITIVE_RE.search(sec_bodies["三、"]):
            return False, "必交章节 '三、' 缺少文献定位与竞品基线审计内容"
        scores_ok, scores_err = _validate_arr_scores(sec_bodies["五、"])
        if not scores_ok:
            return False, scores_err

    elif report_type == "auditor":
        sec1_text = sec_bodies["一、"]
        if not AUDITOR_SEC1_CMD_RE.search(sec1_text):
            return False, "必交章节 '一、' 缺少已执行的对账脚本或命令记录（如 python3 / submission_precheck.py）"
        scr_ok, scr_err = verify_referenced_scripts_exist(sec1_text, workdir)
        if not scr_ok:
            return False, scr_err
        gt_decimals = (
            _collect_ground_truth_decimals(workdir, task_md)
            if (workdir is not None or task_md is not None)
            else None
        )
        mat_ok, mat_err = validate_auditor_sec1_matrix(
            sec1_text, verdict=verdict, ground_truth_decimals=gt_decimals
        )
        if not mat_ok:
            return False, mat_err
        if not AUDITOR_SEC2_POSITIVE_RE.search(sec_bodies["二、"]):
            return False, "必交章节 '二、' 缺少符号/边界/认知流审查证据"
        if verdict == "无阻断":
            for ln, _ in body_items:
                if has_auditor_mismatch_or_fail(ln):
                    return False, f"审计报告存在 MISMATCH/FAIL/不一致 记录（含代码块内），不得判为无阻断：{ln!r}"
            if not AUDITOR_SEC1_POSITIVE_RE.search(sec1_text):
                return False, "必交章节 '一、' 缺少正向数值对账结论状态（如一致/PASS/零误差）"
            if not AUDITOR_SEC3_POSITIVE_RE.search(sec_bodies["三、"]):
                return False, "必交章节 '三、' 缺少双盲匿名与合规核查正向证据（如零泄漏/PASS/合规）"
        else:
            if not AUDITOR_SEC3_ANY_EVIDENCE_RE.search(sec_bodies["三、"]):
                return False, "必交章节 '三、' 缺少双盲匿名与合规核查结果"

    return True, ""


def _is_auditor_unexecuted_line(line: str) -> bool:
    """判断单行是否表明审查者自身未能读取材料或未执行对账（排除行内代码引用与针对被审对象缺陷的描述）。"""
    ln_no_code = INLINE_CODE_RE.sub("", line)
    for pat in AUDITOR_UNEXECUTED_PATTERNS:
        for m in pat.finditer(ln_no_code):
            prefix = ln_no_code[: m.start()]
            if TARGET_DEFECT_SUBJECT_RE.search(prefix):
                continue
            return True
    return False


def parse_final_verdict(
    text: str,
    report_type: str = "any",
    workdir: pathlib.Path | None = None,
    task_md: pathlib.Path | None = None,
) -> tuple[bool, str]:
    """Fail-closed 解析审查报告的章节完整性与末行独立总体判定。"""
    if report_type not in REQUIRED_SECTIONS_BY_TYPE:
        return False, f"未知的报告类型：{report_type!r}"

    raw_lines = text.splitlines()
    non_empty_all = [ln.strip() for ln in raw_lines if ln.strip()]
    if not non_empty_all:
        return False, "报告为空"

    parsed_lines, fences_closed = parse_lines_with_fence_state(raw_lines)
    if not fences_closed:
        return False, "报告存在未闭合的代码围栏"

    non_empty_items = [(ln.strip(), in_fence) for _, ln, in_fence in parsed_lines if ln.strip()]
    outside_non_empty = [ln for ln, in_fence in non_empty_items if not in_fence]
    if not outside_non_empty:
        return False, "报告在代码围栏外无有效内容"

    last_line = non_empty_all[-1]
    if last_line != outside_non_empty[-1]:
        return False, "报告末行位于代码围栏内部，不构成有效独立总体判定"

    if last_line not in EXACT_VERDICTS:
        return (
            False,
            f"末行必须严格为『**总体判定：无阻断**』或『**总体判定：有阻断**』，实得：{last_line!r}",
        )

    if len(outside_non_empty) < 2:
        return False, "报告缺少正文，仅含单行总体判定"

    verdict = EXACT_VERDICTS[last_line]
    body_items = non_empty_items[:-1]

    for ln, in_fence in body_items:
        ln_no_inline_code = INLINE_CODE_RE.sub("", ln)
        for crash_pat in CLI_CRASH_PATTERNS:
            if crash_pat.search(ln_no_inline_code):
                return False, f"报告包含 CLI/沙盒/鉴权崩溃标记：{ln!r}"

        if _is_auditor_unexecuted_line(ln):
            return False, f"报告包含未读取材料、静态阅读/后续补交或未执行对账标记（审查未完成）：{ln!r}"

        if verdict == "无阻断" and has_active_blocker_on_line(ln):
            return False, f"报告正文或代码块存在未豁免的阻断项但末行判为无阻断：{ln!r}"

        if not in_fence:
            if LOOSE_VERDICT_TOKEN_RE.search(ln_no_inline_code):
                if ln not in EXACT_VERDICTS:
                    return False, f"存在格式不合规的总体判定行（必须严格带双星号且独占一行无标点）：{ln!r}"
                if EXACT_VERDICTS[ln] != verdict:
                    return False, f"全文存在前后矛盾的独立总体判定行：{ln!r} vs {last_line!r}"

    required_sections = REQUIRED_SECTIONS_BY_TYPE[report_type]
    sec_ok, sec_err = _validate_required_sections(
        body_items, required_sections, report_type, verdict, workdir=workdir, task_md=task_md
    )
    if not sec_ok:
        return False, sec_err

    return verdict == "无阻断", verdict


# 路径提取正则：覆盖 Markdown 链接目标、反引号包裹路径（含空格与中文）、引号包裹路径，以及含扩展名或路径分隔符的连续非空白串
PATH_CANDIDATE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\]\(([^)\n]+)\)"),
    re.compile(r"`([^`\n]+)`"),
    re.compile(r"[\"'「『]([^\"'」』\n]+)[\"'」』]"),
    re.compile(r"(?<![A-Za-z0-9_])(?:/[^\s`'\"()[\]{}<>,;:，、。；：！？]+|(?:[^\s`'\"()[\]{}<>,;:，、。；：！？]+/)+[^\s`'\"()[\]{}<>,;:，、。；：！？]+|[^\s`'\"()[\]{}<>,;:，、。；：！？]+\.(?:tex|typ|md|json|csv|bib|py|sh|yaml|yml|txt))"),
)
PUNCT_STRIP_CHARS = "`'\"()[]{}<>.,;:，、。；：！？"


def collect_protected_files(
    task_md: pathlib.Path,
    workdir: pathlib.Path,
    out_md: pathlib.Path,
    extra_inputs: list[pathlib.Path] | None = None,
) -> tuple[list[pathlib.Path], set[pathlib.Path]]:
    """收集工作目录、控制文件、显式附加输入及送审说明中引用的全部既有文件路径，并拦截既有文件或悬空符号链接作为 out_md 及其附属日志路径。"""
    task_resolved = task_md.resolve()
    workdir_resolved = workdir.resolve()
    out_abs = pathlib.Path(os.path.abspath(str(out_md)))
    out_real = pathlib.Path(os.path.realpath(str(out_md)))

    out_family: set[pathlib.Path] = set()
    for suffix in ("", ".diag.log", ".exec.log"):
        cand_raw = pathlib.Path(str(out_md) + suffix)
        cand_abs = pathlib.Path(os.path.abspath(str(cand_raw)))
        cand_real = pathlib.Path(os.path.realpath(str(cand_raw)))
        if os.path.lexists(str(cand_raw)) or os.path.lexists(str(cand_abs)) or os.path.lexists(str(cand_real)):
            raise ValueError(
                f"输出报告或附属日志路径已存在或为悬空符号链接（拒绝覆盖或穿透符号链接写入）: {cand_raw}"
            )
        out_family.add(cand_abs)
        out_family.add(cand_real)

    task_text = task_resolved.read_text(encoding="utf-8", errors="ignore")
    candidate_bases = [workdir_resolved, task_resolved.parent, pathlib.Path.cwd().resolve()]

    referenced_resolved: set[pathlib.Path] = set()
    raw_candidates: list[str] = []
    for pat in PATH_CANDIDATE_PATTERNS:
        for m in pat.finditer(task_text):
            raw_candidates.append(m.group(1) if m.lastindex else m.group(0))

    for cand in raw_candidates:
        cleaned = cand.strip().strip(PUNCT_STRIP_CHARS).strip()
        cleaned = re.sub(r"(?:#L\d+(?:-L?\d+)?|:\d+(?::\d+)?)$", "", cleaned)
        if not cleaned or cleaned.startswith(("http://", "https://", "mailto:")):
            continue
        p_raw = pathlib.Path(cleaned)
        if p_raw.is_absolute():
            referenced_resolved.add(pathlib.Path(os.path.abspath(str(p_raw))))
            referenced_resolved.add(pathlib.Path(os.path.realpath(str(p_raw))))
        else:
            for base in candidate_bases:
                referenced_resolved.add(pathlib.Path(os.path.abspath(str(base / p_raw))))
                referenced_resolved.add(pathlib.Path(os.path.realpath(str(base / p_raw))))

    for extra in extra_inputs or []:
        referenced_resolved.add(pathlib.Path(os.path.abspath(str(extra))))
        referenced_resolved.add(pathlib.Path(os.path.realpath(str(extra))))

    if (out_family & referenced_resolved) or (out_family & {task_resolved, workdir_resolved}):
        raise ValueError(f"输出报告或附属日志路径与受保护的送审输入路径重合: {out_abs}")

    tracked_files: set[pathlib.Path] = {task_resolved}
    for root_dir in [workdir_resolved]:
        for dirpath, _, filenames in os.walk(root_dir, followlinks=True):
            for fn in filenames:
                fp = pathlib.Path(dirpath) / fn
                if fp.is_file():
                    tracked_files.add(fp.resolve())

    for ref in referenced_resolved:
        if ref.is_file():
            tracked_files.add(ref.resolve())
        elif ref.is_dir():
            for dirpath, _, filenames in os.walk(ref, followlinks=True):
                for fn in filenames:
                    fp = pathlib.Path(dirpath) / fn
                    if fp.is_file():
                        tracked_files.add(fp.resolve())

    return sorted(tracked_files, key=lambda x: str(x)), referenced_resolved


def compute_files_snapshot(
    tracked_list_file: pathlib.Path,
    workdir: pathlib.Path,
    ignore_out: pathlib.Path | None = None,
) -> str:
    """根据受保护文件清单与当前工作目录计算确定性 SHA-256 快照文本。"""
    ignore_set: set[pathlib.Path] = set()
    if ignore_out is not None:
        for suffix in ("", ".diag.log", ".exec.log"):
            cand_ignore = pathlib.Path(str(ignore_out) + suffix)
            ignore_set.add(pathlib.Path(os.path.abspath(str(cand_ignore))))
            ignore_set.add(pathlib.Path(os.path.realpath(str(cand_ignore))))

    files: set[pathlib.Path] = set()
    for line in tracked_list_file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            files.add(pathlib.Path(line.strip()))

    for dirpath, _, filenames in os.walk(workdir.resolve(), followlinks=True):
        for fn in filenames:
            raw_fp = pathlib.Path(dirpath) / fn
            fp_abs = pathlib.Path(os.path.abspath(str(raw_fp)))
            fp_real = pathlib.Path(os.path.realpath(str(raw_fp)))
            if fp_abs in ignore_set or fp_real in ignore_set:
                continue
            files.add(fp_real if raw_fp.exists() else fp_abs)

    rows: list[str] = []
    for fp in sorted(files, key=lambda x: str(x)):
        if pathlib.Path(os.path.abspath(str(fp))) in ignore_set or pathlib.Path(os.path.realpath(str(fp))) in ignore_set:
            continue
        if not fp.exists():
            rows.append(f"MISSING  {fp}")
        elif fp.is_file():
            h = hashlib.sha256(fp.read_bytes()).hexdigest()
            rows.append(f"{h}  {fp}")
    return "\n".join(rows) + "\n"


PRECHECK_EXEC_EVENT_RE = re.compile(
    r"(?ms)^exec\s*\n"
    r"/bin/(?:ba)?sh\s+-lc\s+['\"]?\s*python3?\s+(?!-c\b)[^\n;|&]*?submission_precheck\.py\b[^\n;|&]*?(?:\n\s*)?succeeded\s+in\s+\d+\s*ms:\s*\n"
    r"\{\s*\n\s*\"manuscripts\"\s*:\s*\[\s*\n\s*\{\s*\n\s*\"file\"\s*:\s*\"[^\"]+\".*?\n\s*\"n_summaries_loaded\"\s*:\s*\d+",
)


def verify_cli_execution_log(
    log_path: pathlib.Path, prompt_path: pathlib.Path | None = None
) -> tuple[bool, str]:
    """核验 CLI 运行日志中除回显提示词外，必须包含真实执行 submission_precheck.py 命令并紧随其后产出 JSON 扫描结果（含 \"manuscripts\" 列表对象与整型 \"n_summaries_loaded\"）的完整命令事件块。
    从而拦截仅运行 pwd/ls、仅用 sed/cat 读取脚本源码，或仅回显提示词的伪执行日志。
    """
    if not log_path.is_file():
        return False, "运行日志不存在"
    log_text = log_path.read_text(encoding="utf-8", errors="ignore")
    prompt_text = (
        prompt_path.read_text(encoding="utf-8", errors="ignore")
        if (prompt_path is not None and prompt_path.is_file())
        else ""
    )
    stripped = log_text
    if prompt_text:
        stripped = stripped.replace(prompt_text, "")
        for pline in prompt_text.splitlines():
            p_clean = pline.strip()
            if len(p_clean) >= 12:
                stripped = stripped.replace(p_clean, "")

    if PRECHECK_EXEC_EVENT_RE.search(stripped):
        return True, ""
    return (
        False,
        "运行日志（剔除提示词回显后）缺少真实执行 submission_precheck.py 并紧随产出 JSON 扫描结果的命令事件块",
    )


def scan_manuscript(path: pathlib.Path) -> dict[str, Any]:
    """扫描单份稿件的双盲泄漏、合规章节标题与表格数值概览。"""
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    leaks: list[dict[str, Any]] = []
    for idx, line in enumerate(lines, 1):
        for rule_id, pat, note in LEAK_PATTERNS:
            m = pat.search(line)
            if m:
                leaks.append(
                    {
                        "line": idx,
                        "rule": rule_id,
                        "match": m.group(0),
                        "note": note,
                    }
                )

    headings = extract_headings(lines)
    compliance: dict[str, bool] = {}
    for label, hpat in COMPLIANCE_HEADING_RULES:
        compliance[label] = any(hpat.search(h) for h in headings)

    repro_heading_ok = any(REPRO_HEADING_RE.search(h) for h in headings)
    repro_params_count = sum(1 for p in REPRO_PARAM_MARKERS if p.search(text))
    compliance["Reproducibility（可复现性章节标题 + 至少 2 项采样/统计超参说明）"] = (
        repro_heading_ok and repro_params_count >= 2
    )

    table_lines = [idx for idx, ln in enumerate(lines, 1) if "|" in ln or "\\begin{tabular}" in ln]
    return {
        "file": str(path),
        "n_lines": len(lines),
        "n_headings": len(headings),
        "n_table_lines": len(table_lines),
        "leaks": leaks,
        "compliance": compliance,
    }


def extract_json_metrics(json_paths: list[pathlib.Path]) -> dict[str, Any]:
    """从 summary_*.json 提取关键确认性指标供三方对账使用。"""
    extracted: dict[str, Any] = {}
    for jp in json_paths:
        data = json.loads(jp.read_text(encoding="utf-8"))
        extracted[jp.name] = data
    return extracted


class PrecheckSelfTest(unittest.TestCase):
    def test_verdict_pass(self) -> None:
        ok, msg = parse_final_verdict("# 审查报告\n正文一切正常。\n\n**总体判定：无阻断**\n")
        self.assertTrue(ok)
        self.assertEqual(msg, "无阻断")

    def test_verdict_blocker(self) -> None:
        ok, msg = parse_final_verdict("# 审查报告\n发现数值错位。\n\n**总体判定：有阻断**\n")
        self.assertFalse(ok)
        self.assertEqual(msg, "有阻断")

    def test_valid_negative_report_describing_target_defect_is_accepted(self) -> None:
        neg_report = (
            "# 审计报告\n"
            "## 一、对账\n"
            "已执行命令：`python3 submission_precheck.py paper.tex --summaries summary_formal.json`\n"
            "| 表 1 | H1 | 0.842 | 0.842 | 0.000 | PASS |\n"
            "## 二、符号\n符号与边界正常。\n"
            "## 三、匿名\n匿名零泄漏（PASS）。\n"
            "## 四、修复\n"
            "- [Blocker 阻断] 已执行测试并确认：待审解析器无法读取含空值的 CSV。\n"
            "**总体判定：有阻断**\n"
        )
        ok, detail = parse_final_verdict(neg_report, report_type="auditor")
        self.assertFalse(ok)
        self.assertEqual(detail, "有阻断")

        # 反之，若负面报告自身写『未执行数值对账』且其余章节写『略』，必须作为未完成报告拒收
        unexecuted_neg = (
            "# 审计报告\n"
            "## 一、对账\n未执行数值对账。\n"
            "## 二、符号\n略\n"
            "## 三、匿名\n略\n"
            "## 四、修复\n略\n"
            "**总体判定：有阻断**\n"
        )
        ok_unexec, detail_unexec = parse_final_verdict(unexecuted_neg, report_type="auditor")
        self.assertFalse(ok_unexec)
        self.assertNotIn(detail_unexec, ("无阻断", "有阻断"))

    def test_verdict_ignores_fenced_and_inline_code_examples(self) -> None:
        text = (
            "# 审查报告\n"
            "反例说明：当末行写为 `**总体判定：无阻断**` 时：\n"
            "```text\n"
            "**总体判定：无阻断**\n"
            "```\n"
            "正文结论。\n"
            "**总体判定：有阻断**\n"
        )
        ok, msg = parse_final_verdict(text)
        self.assertFalse(ok)
        self.assertEqual(msg, "有阻断")

    def test_verdict_rejects_malformed_variants(self) -> None:
        for bad_line in ("总体判定: 无阻断.", "**总体判定：无阻断", "总体判定：无阻断**"):
            ok, _ = parse_final_verdict(f"# 审查报告\n正文内容。\n{bad_line}\n")
            self.assertFalse(ok, f"应拒绝不合规末行: {bad_line!r}")

    def test_verdict_rejects_single_line_stub(self) -> None:
        ok, msg = parse_final_verdict("**总体判定：无阻断**\n")
        self.assertFalse(ok)
        self.assertIn("缺少正文", msg)

    def test_verdict_rejects_inline_enumeration_and_empty_sections(self) -> None:
        bad_inline = "尚无法读取稿件。一、二、三、四、\n**总体判定：无阻断**\n"
        self.assertFalse(parse_final_verdict(bad_inline, report_type="auditor")[0])

        bad_inline_no_disclaimer = "正常前言。一、二、三、四、\n**总体判定：无阻断**\n"
        self.assertFalse(parse_final_verdict(bad_inline_no_disclaimer, report_type="auditor")[0])

        empty_arr = "## 一、总结\n## 二、混淆\n## 三、文献\n## 四、问题\n## 五、评分\n**总体判定：无阻断**\n"
        self.assertFalse(parse_final_verdict(empty_arr, report_type="arr")[0])

    def test_verdict_rejects_failure_markers_and_blocker_contradiction(self) -> None:
        base_sections = (
            "## 一、对账\n"
            "执行命令：`python3 submission_precheck.py paper.tex --summaries summary_formal.json`\n"
            "| 表 1 | H1 | 0.842 | 0.842 | 0.000 | PASS |\n"
            "{line1}\n"
            "## 二、符号\n符号与边界正常。\n"
            "## 三、匿名\n匿名零泄漏（PASS）。\n"
            "## 四、修复\n{line4}\n"
            "**总体判定：无阻断**\n"
        )
        for unread_or_unexecuted in (
            "failed to spawn code-mode host",
            "无法读取实验数据，未运行任何对账命令。",
            "原始 JSON 无法访问，尚未执行数值对账。",
            "仅作静态阅读；对账命令与逐格差值将于后续补交。",
            "Raw JSON is inaccessible and numerical reconciliation was not executed.",
            "Could not read summary_formal.json; reconciliation check is incomplete.",
            "| 表 1 | H1 | 0.42 | 0.39 | +0.03 | MISMATCH |",
            "| 表 1 | H1 | 0.42 | 0.39 | +0.03 | `MISMATCH` |",
            "```text\n0.42 | 0.39 | +0.03 | MISMATCH\n```",
            "| 匿名 | 作者邮箱未匿名化 | `FAIL` |",
            "| 匿名：作者邮箱仍暴露 | FAIL",
            "匿名检查 FAIL（作者邮箱仍然暴露）",
            "模型 A 的 **0.42 与 JSON 原件 0.39 不一致**，但表格其余一致（PASS）。",
        ):
            case_bad = base_sections.format(line1=unread_or_unexecuted, line4="无。")
            self.assertFalse(
                parse_final_verdict(case_bad, report_type="auditor")[0],
                f"应拒绝未完成或含 MISMATCH/FAIL 的报告: {unread_or_unexecuted!r}",
            )

        for blocker_line in (
            "- [Blocker 阻断] 表 1 数值与 JSON 原件不一致。",
            "| [Blocker 阻断] | 表 1 | 数值与原件不一致 |",
            "1) [Blocker 阻断] 表 1 数值错误。",
            "- [Blocker 阻断] 表 1 存在数值错误；表 2 无 [Blocker]。",
            "[Blocker] 摘要核心宣称无实验数据支持。",
            "按 [Blocker 阻断] 记录：表 1 与 JSON 原件数值不一致。",
            "共 **10 项** `[Blocker]` 需要修复。",
        ):
            case_conflict = base_sections.format(line1="全部 28 项数字一致（PASS）。", line4=blocker_line)
            self.assertFalse(
                parse_final_verdict(case_conflict, report_type="auditor")[0],
                f"应拒绝包含未豁免阻断项却判为无阻断的报告: {blocker_line!r}",
            )

    def test_auditor_requires_executed_command_matrix_and_numeric_consistency(self) -> None:
        # 1. MISMATCH inside fenced code block must be rejected
        fenced_mismatch = (
            "## 一、对账\n"
            "已执行 `python3 submission_precheck.py paper.tex`\n"
            "```text\n"
            "0.42 | 0.39 | +0.03 | MISMATCH\n"
            "```\n"
            "## 二、符号\n符号无冲突。\n"
            "## 三、匿名\n零泄漏（PASS）。\n"
            "## 四、修复\n无。\n"
            "**总体判定：无阻断**\n"
        )
        self.assertFalse(parse_final_verdict(fenced_mismatch, report_type="auditor")[0])

        # 2. Static reading / deferred reconciliation must be rejected
        static_deferred = (
            "## 一、对账\n"
            "仅作静态阅读；对账命令与逐格差值将于后续补交。\n"
            "## 二、符号\n符号无冲突。\n"
            "## 三、匿名\n零泄漏（PASS）。\n"
            "## 四、修复\n无。\n"
            "**总体判定：无阻断**\n"
        )
        self.assertFalse(parse_final_verdict(static_deferred, report_type="auditor")[0])

        # 3. All counterexamples from Rounds 11, 12, and 13
        for bad_row in (
            "| 表 1 | H2 | $0.42$ | $0.39$ | $0.03$ | PASS |",
            "| 表 1 | H2 | 0.842% | 0.842 | 0.000 | PASS |",
            "| 表 1 | H2 | 0.100 | 0.10052 | -0.00052 | PASS |",
            "| 表 1 | H2 | 0.149 | 0.1 | 0.049 | PASS |",
            "| 表 1 | H2 | 1.234e-9 | 9.876e-9 | -8.642e-9 | PASS |",
            "| 表 1 | H2 | 0.842 | 0.100 | 0.742 | PASS（已核对） |",
            "| 表 1 | H2 | 0.842 | 0.100 | 0.000 | PASS（状态可选 PASS / MISMATCH） |",
            "| 表 1 | H2 | 0.842 | 0.8416 | -0.0004 | PASS |",
            "| 表 1 | H2 | 120 | 119 | 1 | PASS |",
            "| 表 1 | H2 | 0.842 | 0.842 | PASS |",
        ):
            mixed_report = (
                "## 一、对账\n"
                "已执行 `python3 submission_precheck.py paper.tex --summaries summary_formal.json`\n"
                "| 位置 | 指标 | 稿件数值 | 原件数值 | 差值 | 状态 |\n"
                "|---|---|---|---|---|---|\n"
                "| 表 1 | H1 | 0.842 | 0.842 | 0.000 | PASS |\n"
                f"{bad_row}\n"
                "## 二、符号\n符号无冲突。\n"
                "## 三、匿名\n零泄漏（PASS）。\n"
                "## 四、修复\n无。\n"
                "**总体判定：无阻断**\n"
            )
            self.assertFalse(
                parse_final_verdict(mixed_report, report_type="auditor")[0],
                f"应拒绝包含错误矩阵行的报告: {bad_row!r}",
            )

        # 3b. Valid integer rounding from continuous decimal (42 vs 41.8, diff +0.2 or 0.2) must be accepted
        int_round_ok = (
            "## 一、对账\n"
            "已执行 `python3 submission_precheck.py paper.tex --summaries summary_formal.json`\n"
            "| 位置 | 指标 | 稿件数值 | 原件数值 | 差值 | 状态 |\n"
            "|---|---|---|---|---|---|\n"
            "| 表 1 | 均值 | 42 | 41.8 | +0.2 | PASS |\n"
            "| 表 1 | H1 | 0.842 | 0.8416 | +0.0004 | PASS |\n"
            "## 二、符号\n符号无冲突。\n"
            "## 三、匿名\n零泄漏（PASS）。\n"
            "## 四、修复\n无。\n"
            "**总体判定：无阻断**\n"
        )
        self.assertTrue(parse_final_verdict(int_round_ok, report_type="auditor")[0])

        # 3c. Negative report with arithmetically inconsistent MISMATCH diff (0.842 | 0.100 | 0.000 | MISMATCH) must be rejected
        bad_neg_mismatch_diff = (
            "## 一、对账\n"
            "已执行 `python3 submission_precheck.py paper.tex --summaries summary_formal.json`\n"
            "| 位置 | 指标 | 稿件数值 | 原件数值 | 差值 | 状态 |\n"
            "|---|---|---|---|---|---|\n"
            "| 表 1 | H1 | 0.842 | 0.100 | 0.000 | MISMATCH |\n"
            "## 二、符号\n符号无冲突。\n"
            "## 三、匿名\n零泄漏（PASS）。\n"
            "## 四、修复\n- [Blocker 阻断] 表 1 数值不一致。\n"
            "**总体判定：有阻断**\n"
        )
        self.assertNotIn(
            parse_final_verdict(bad_neg_mismatch_diff, report_type="auditor")[1],
            ("无阻断", "有阻断"),
        )

        # 4. Non-existent script or fabricated source JSON numbers in section 1 must be rejected when workdir is supplied
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            wdir = pathlib.Path(tmp)
            (wdir / "summary_formal.json").write_text('{"H1": 0.915, "n": 120}', encoding="utf-8")
            fake_script_report = (
                "## 一、对账\n"
                "已执行 `python3 reconcile_nonexistent.py paper.tex`\n"
                "| 位置 | 指标 | 稿件数值 | 原件数值 | 差值 | 状态 |\n"
                "|---|---|---|---|---|---|\n"
                "| 表 1 | H1 | 0.915 | 0.915 | 0.000 | PASS |\n"
                "## 二、符号\n符号无冲突。\n"
                "## 三、匿名\n零泄漏（PASS）。\n"
                "## 四、修复\n无。\n"
                "**总体判定：无阻断**\n"
            )
            ok_fake, err_fake = parse_final_verdict(
                fake_script_report, report_type="auditor", workdir=wdir
            )
            self.assertFalse(ok_fake)
            self.assertIn("不存在", err_fake)

            # Fabricated source number 0.842 not in summary_formal.json (which only has 0.915 and 120) must be rejected
            fabricated_num_report = (
                "## 一、对账\n"
                "已执行 `python3 submission_precheck.py paper.tex --summaries summary_formal.json`\n"
                "| 位置 | 指标 | 稿件数值 | 原件数值 | 差值 | 状态 |\n"
                "|---|---|---|---|---|---|\n"
                "| 表 1 | H1 | 0.842 | 0.842 | 0.000 | PASS |\n"
                "## 二、符号\n符号无冲突。\n"
                "## 三、匿名\n零泄漏（PASS）。\n"
                "## 四、修复\n无。\n"
                "**总体判定：无阻断**\n"
            )
            ok_fab, err_fab = parse_final_verdict(
                fabricated_num_report, report_type="auditor", workdir=wdir
            )
            self.assertFalse(ok_fab)
            self.assertIn("未找到匹配项", err_fab)

            # Workdir without any JSON/CSV files (or with only empty {} JSON / single-line or multiline header-only CSV) must also fail closed
            empty_wdir = wdir / "no_json_dir"
            empty_wdir.mkdir()
            (empty_wdir / "empty.json").write_text("{}", encoding="utf-8")
            (empty_wdir / "header_only.csv").write_text("metric,2026\n", encoding="utf-8")
            (empty_wdir / "multiline_header_only.csv").write_text('"metric\n2026",value\n', encoding="utf-8")
            for fake_val in ("0", "2026"):
                zero_row_report = fabricated_num_report.replace(
                    "| 表 1 | H1 | 0.842 | 0.842 | 0.000 | PASS |",
                    f"| 表 1 | H1 | {fake_val} | {fake_val} | 0 | PASS |",
                )
                ok_no_gt, err_no_gt = parse_final_verdict(
                    zero_row_report, report_type="auditor", workdir=empty_wdir
                )
                self.assertFalse(ok_no_gt)
                self.assertIn("未在工作目录或送审说明中找到任何可用的 JSON/CSV", err_no_gt)

    def test_verdict_report_type_sections(self) -> None:
        arr_ok = (
            "# 报告\n"
            "## 一、总结\n"
            "已核对全文 3 项宣称，证据闭合。\n"
            "| 编号 | 宣称 | 证据 | 闭合度 |\n"
            "|---|---|---|---|\n"
            "| C1 | 摘要宣称校准提升 | 表 1 (n=120) | 闭合 |\n"
            "## 二、混淆\n"
            "已排查 CoT 与框架混淆。\n"
            "| 维度 | 攻击角度 | 防御状态 | 建议 |\n"
            "|---|---|---|---|\n"
            "| 推理长度混淆 | CoT 词元数差异 | 已排除 | 表 2 受控消融 |\n"
            "## 三、文献\n已核查 lit_kb 竞品。\n"
            "## 四、问题\n无 [Blocker 阻断] 问题。\n"
            "## 五、评分\n"
            "- Soundness: 4/5\n"
            "- Excitement: 4/5\n"
            "- Overall Assessment: 4/5\n"
            "- Reviewer Confidence: 4/5\n"
            "**总体判定：无阻断**\n"
        )
        self.assertTrue(parse_final_verdict(arr_ok, report_type="arr")[0])

        # 只有表头和分隔线、无实质数据行的 ARR 报告必须拒绝
        arr_header_only = arr_ok.replace("| C1 | 摘要宣称校准提升 | 表 1 (n=120) | 闭合 |\n", "")
        self.assertFalse(parse_final_verdict(arr_header_only, report_type="arr")[0])

        # 评分越界（如 50/5、0/5、6/5）必须拒绝
        for bad_score in ("50/5", "0/5", "6/5", "4/10"):
            arr_bad_score = arr_ok.replace("Soundness: 4/5", f"Soundness: {bad_score}")
            self.assertFalse(
                parse_final_verdict(arr_bad_score, report_type="arr")[0],
                f"应拒绝越界评分: {bad_score}",
            )

        # 缺少表格或四项评分的 ARR 报告（无论无阻断或有阻断）均须拒绝为不完整
        arr_missing_table_neg = (
            "# 报告\n"
            "## 一、总结\n仅文字无宣称表格。\n"
            "## 二、混淆\n仅文字无混淆矩阵。\n"
            "## 三、文献\n已核查 lit_kb 竞品。\n"
            "## 四、问题\n- [Blocker 阻断] 某问题。\n"
            "## 五、评分\n"
            "- Soundness: 2/5\n- Excitement: 2/5\n- Overall Assessment: 2/5\n- Reviewer Confidence: 4/5\n"
            "**总体判定：有阻断**\n"
        )
        self.assertEqual(parse_final_verdict(arr_missing_table_neg, report_type="arr")[0], False)
        self.assertNotIn(parse_final_verdict(arr_missing_table_neg, report_type="arr")[1], ("无阻断", "有阻断"))

        aud_ok = (
            "# 报告\n"
            "## 一、对账\n"
            "已执行命令：`python3 submission_precheck.py paper.tex --summaries summary_formal.json`\n"
            "| 位置 | 指标 | 稿件数值 | 原件数值 | 差值 | 状态（PASS / MISMATCH） |\n"
            "|---|---|---|---|---|---|\n"
            "| 表 1 | H1 | 0.842 | 0.842 | 0.000 | PASS（已核对） |\n"
            "全部 28 项数字一致（PASS），**未发现不一致**。\n"
            "## 二、符号\n符号无冲突，边界良定义。\n"
            "## 三、匿名\n零泄漏（PASS）。\n"
            "## 四、修复\n0 项 [Blocker] 修复项；[Blocker 阻断]：无。\n"
            "**总体判定：无阻断**\n"
        )
        self.assertTrue(parse_final_verdict(aud_ok, report_type="auditor")[0])

    def test_collect_protected_files_json_chinese_spaces_and_dangling_symlink(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            workdir = root / "work"
            ext_dir = root / "evidence"
            cn_dir = root / "中文目录"
            sp_dir = root / "path with spaces"
            workdir.mkdir()
            ext_dir.mkdir()
            cn_dir.mkdir()
            sp_dir.mkdir()

            paper = workdir / "paper.tex"
            paper.write_text("hello", encoding="utf-8")
            ext_json = ext_dir / "summary_formal.json"
            ext_json.write_text('{"auc": 0.842}', encoding="utf-8")
            cn_json = cn_dir / "实验汇总_formal.json"
            cn_json.write_text('{"n": 120}', encoding="utf-8")
            sp_csv = sp_dir / "table results.csv"
            sp_csv.write_text("a,b\n1,2\n", encoding="utf-8")

            task_md = root / "task.md"
            task_md.write_text(
                f"请核对 {ext_json}、\"{cn_json}\" 以及 `{sp_csv}`。\n",
                encoding="utf-8",
            )
            out_md = root / "new_report.md"

            tracked, _ = collect_protected_files(task_md, workdir, out_md)
            tracked_set = set(tracked)
            self.assertIn(ext_json.resolve(), tracked_set)
            self.assertIn(cn_json.resolve(), tracked_set)
            self.assertIn(sp_csv.resolve(), tracked_set)

            # 既有悬空符号链接或附属日志（.diag.log / .exec.log）已存在时作为输出路径必须被拒绝
            dangling = root / "dangling_report.md"
            dangling.symlink_to(root / "nonexistent_target.md")
            with self.assertRaises(ValueError):
                collect_protected_files(task_md, workdir, dangling)

            out_with_existing_exec_log = root / "report_with_log.md"
            pathlib.Path(str(out_with_existing_exec_log) + ".exec.log").write_text("old", encoding="utf-8")
            with self.assertRaises(ValueError):
                collect_protected_files(task_md, workdir, out_with_existing_exec_log)

            # 模拟仅回显提示词、仅执行 pwd 或仅用 sed 读取本脚本源码的日志必须被 verify_cli_execution_log 拦截
            echo_only_log = root / "echo_only.log"
            echo_only_log.write_text(task_md.read_text(encoding="utf-8"), encoding="utf-8")
            self.assertFalse(verify_cli_execution_log(echo_only_log, task_md)[0])

            pwd_only_log = root / "pwd_only.log"
            pwd_only_log.write_text(
                task_md.read_text(encoding="utf-8") + "\nexec\n/bin/bash -lc pwd\nsucceeded in 10ms:\n/tmp\n",
                encoding="utf-8",
            )
            self.assertFalse(verify_cli_execution_log(pwd_only_log, task_md)[0])

            sed_source_log = root / "sed_source.log"
            sed_source_log.write_text(
                task_md.read_text(encoding="utf-8")
                + "\nexec\n/bin/bash -lc 'sed -n \"1,2000p\" submission_precheck.py' succeeded in 12ms:\n"
                + pathlib.Path(__file__).read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            self.assertFalse(verify_cli_execution_log(sed_source_log, task_md)[0])

            real_exec_log = root / "real_exec.log"
            sample_json_out = json.dumps(
                {"manuscripts": [{"file": "paper.tex"}], "n_summaries_loaded": 1}, indent=2
            )
            real_exec_log.write_text(
                task_md.read_text(encoding="utf-8")
                + '\nexec\n/bin/bash -lc "python3 submission_precheck.py paper.tex --summaries summary_formal.json" succeeded in 25ms:\n'
                + sample_json_out
                + "\n",
                encoding="utf-8",
            )
            self.assertTrue(verify_cli_execution_log(real_exec_log, task_md)[0])

    def test_verdict_contradiction_rejected(self) -> None:
        text = "# 报告\n**总体判定：无阻断**\n本轮复核：\n**总体判定：有阻断**\n"
        ok, msg = parse_final_verdict(text)
        self.assertFalse(ok)
        self.assertIn("矛盾", msg)

    def test_verdict_inline_substring_not_accepted(self) -> None:
        text = "# 报告\n虽然前文提到总体判定：无阻断，但末行未按格式收尾。"
        ok, _ = parse_final_verdict(text)
        self.assertFalse(ok)

    def test_scan_manuscript_headings_and_leaks(self) -> None:
        import tempfile

        sample = (
            "# Introduction\n"
            "We mention limitations and ethics and temperature in passing.\n"
            "```markdown\n"
            "# Limitations\n"
            "# Ethical Considerations\n"
            "# Experimental Setup\n"
            "```\n"
            + "Path leak: C" + r":\Users\alice\secret\paper.tex" + "\n"
            + "= Acknowledgments\n"
            "Thanks to grant X.\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".typ", encoding="utf-8", delete=False) as f:
            f.write(sample)
            tmp_path = pathlib.Path(f.name)
        try:
            res = scan_manuscript(tmp_path)
            rules = {item["rule"] for item in res["leaks"]}
            self.assertIn("windows_user_path", rules)
            self.assertIn("acknowledgments_section", rules)
            self.assertFalse(any(res["compliance"].values()))
        finally:
            tmp_path.unlink(missing_ok=True)

    def test_latex_headings_with_labels_and_comments(self) -> None:
        import tempfile

        latex_doc = (
            r"\section{Introduction}" + "\n"
            r"\section{Experimental Setup}\label{sec:setup}" + "\n"
            "We use temperature=0.0, top_p=1.0, and seed=42.\n"
            r"\section{Limitations}\label{sec:limitations}" + "\n"
            "Our evaluation focuses on English NLI.\n"
            r"\section{Ethical Considerations} % required by ARR" + "\n"
            "All datasets are public.\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".tex", encoding="utf-8", delete=False) as f:
            f.write(latex_doc)
            tmp_path = pathlib.Path(f.name)
        try:
            res = scan_manuscript(tmp_path)
            self.assertEqual(len(res["leaks"]), 0)
            self.assertTrue(all(res["compliance"].values()), f"LaTeX 合规章节应全部识别通过: {res['compliance']}")
        finally:
            tmp_path.unlink(missing_ok=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("manuscripts", nargs="*", type=pathlib.Path, help="待审稿件路径")
    ap.add_argument("--summaries", nargs="*", type=pathlib.Path, default=[], help="核对用 JSON 原件路径")
    ap.add_argument("--check-verdict", type=pathlib.Path, default=None, help="校验审查报告末行总体判定")
    ap.add_argument(
        "--report-type",
        choices=("any", "arr", "auditor"),
        default="any",
        help="校验审查报告必交章节结构（arr 要求五节，auditor 要求四节）",
    )
    ap.add_argument(
        "--workdir",
        type=pathlib.Path,
        default=None,
        help="与 --check-verdict 合用，核验报告中声称执行的脚本与原件数值在工作目录内真实存在",
    )
    ap.add_argument(
        "--task-md",
        type=pathlib.Path,
        default=None,
        help="与 --check-verdict 合用，补充提取送审说明中引用的外部 JSON/CSV 原件供数值对账核验",
    )
    ap.add_argument(
        "--require-pass",
        action="store_true",
        help="与 --check-verdict 合用时，仅在报告合规且判定为『无阻断』时返回 0（有效『有阻断』返回 1，不合规返回 2）",
    )
    ap.add_argument(
        "--verify-exec-log",
        nargs=2,
        metavar=("LOG_FILE", "PROMPT_FILE"),
        help="核验运行日志（剔除提示词后）包含真实工具执行或预检脚本输出记录",
    )
    ap.add_argument(
        "--collect-protected",
        nargs=4,
        metavar=("TASK_MD", "WORKDIR", "OUT_MD", "LIST_OUT"),
        help="收集送审说明与工作目录的受保护文件清单并校验 OUT_MD 无冲突",
    )
    ap.add_argument(
        "--extra-protected",
        nargs="*",
        type=pathlib.Path,
        default=[],
        help="与 --collect-protected 合用的额外受保护输入路径",
    )
    ap.add_argument(
        "--snapshot",
        nargs=3,
        metavar=("LIST_FILE", "WORKDIR", "SNAP_OUT"),
        help="根据受保护文件清单与工作目录生成 SHA-256 快照文件",
    )
    ap.add_argument(
        "--ignore-out",
        type=pathlib.Path,
        default=None,
        help="与 --snapshot 合用时忽略的新生成报告路径",
    )
    ap.add_argument("--selftest", action="store_true", help="运行内置单元测试")
    args = ap.parse_args()

    if args.selftest:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(PrecheckSelfTest)
        res = unittest.TextTestRunner(verbosity=2).run(suite)
        return 0 if res.wasSuccessful() else 1

    if args.verify_exec_log is not None:
        log_p, prompt_p = (pathlib.Path(x) for x in args.verify_exec_log)
        ok_log, err_log = verify_cli_execution_log(log_p, prompt_p)
        if not ok_log:
            print(f"[ERROR] {err_log}", file=sys.stderr)
            return 2
        return 0

    if args.collect_protected is not None:
        task_p, work_p, out_p, list_p = (pathlib.Path(x) for x in args.collect_protected)
        try:
            tracked, _ = collect_protected_files(task_p, work_p, out_p, args.extra_protected)
        except ValueError as exc:
            print(f"[ERROR] {exc}", file=sys.stderr)
            return 2
        list_p.write_text("\n".join(str(x) for x in tracked) + "\n", encoding="utf-8")
        return 0

    if args.snapshot is not None:
        list_p, work_p, snap_p = (pathlib.Path(x) for x in args.snapshot)
        snap_text = compute_files_snapshot(list_p, work_p, args.ignore_out)
        snap_p.write_text(snap_text, encoding="utf-8")
        return 0

    if args.check_verdict is not None:
        text = args.check_verdict.read_text(encoding="utf-8")
        ok, detail = parse_final_verdict(
            text, report_type=args.report_type, workdir=args.workdir, task_md=args.task_md
        )
        valid_format = detail in ("无阻断", "有阻断")
        print(
            json.dumps(
                {
                    "file": str(args.check_verdict),
                    "report_type": args.report_type,
                    "valid_report": valid_format,
                    "approved_no_blockers": ok,
                    "detail": detail,
                },
                ensure_ascii=False,
            )
        )
        if not valid_format:
            return 2
        if args.require_pass and not ok:
            return 1
        return 0

    if not args.manuscripts:
        ap.error("请提供至少一份待审稿件路径，或使用 --selftest / --check-verdict")

    extracted_summaries = extract_json_metrics(args.summaries)
    report = {
        "manuscripts": [scan_manuscript(p) for p in args.manuscripts],
        "n_summaries_loaded": len(extracted_summaries),
        "summary_metrics": extracted_summaries,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
