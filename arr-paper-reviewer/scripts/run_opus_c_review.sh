#!/usr/bin/env bash
# 顶会论文审稿人（前三关 arr-paper-reviewer）独立批判者 c 派发脚本
# 绑定载体：Claude Opus 5.5 (effort=high, 只读无状态沙盒与配置隔离模式)
# 用法：bash run_opus_c_review.sh <送审任务说明_TASK.md> <输出报告_REVIEW.md> [工作目录] [额外受保护输入路径...]
# 退出码：
#   0 = 审查报告生成且结构校验通过（若设置 REQUIRE_NO_BLOCKERS=1，则仅在末行判定为『无阻断』时返回 0）
#   1 = 已设置 REQUIRE_NO_BLOCKERS=1，报告结构有效但末行判定为『有阻断』
#   2 = 参数错误、输出路径冲突或报告未通过完整性校验
#   3 = 未找到可执行的 claude CLI 或缺少操作系统只读沙盒 bwrap（未显式授权降级）
#   4 = CLI 执行失败或鉴权异常（诊断日志保存至 <output_review_md_path>.diag.log）
#   5 = 只读铁律被违反（前后 SHA-256 快照不一致）

set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "用法: $0 <task_md_path> <output_review_md_path> [workdir] [extra_protected_paths...]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_MD="$(realpath "$SCRIPT_DIR/../SKILL.md")"
TASK_MD="$(realpath "$1")"
RAW_OUT_MD="$2"
OUT_MD="$(realpath -m "$RAW_OUT_MD")"
WORKDIR="$(realpath "${3:-$(pwd)}")"
EXTRA_INPUTS=("${@:4}")

EXPECTED_MODEL="claude-opus-5-5"
EXPECTED_EFFORT="high"
MODEL="${OPUS_MODEL:-$EXPECTED_MODEL}"
EFFORT="${OPUS_EFFORT:-$EXPECTED_EFFORT}"

if [ "$MODEL" != "$EXPECTED_MODEL" ] || [ "$EFFORT" != "$EXPECTED_EFFORT" ]; then
  echo "[ERROR] 严禁静默降级或替换模型/推理强度：仅允许 MODEL=$EXPECTED_MODEL 且 EFFORT=$EXPECTED_EFFORT（当前请求: MODEL=$MODEL, EFFORT=$EFFORT）。" >&2
  exit 2
fi

if [ ! -s "$SKILL_MD" ]; then
  echo "[ERROR] 找不到技能规则文件: $SKILL_MD" >&2
  exit 2
fi

if [ ! -f "$TASK_MD" ]; then
  echo "[ERROR] 找不到送审说明文件: $TASK_MD" >&2
  exit 2
fi

if [ ! -d "$WORKDIR" ]; then
  echo "[ERROR] 找不到待审工作目录: $WORKDIR" >&2
  exit 2
fi

for p_chk in "$RAW_OUT_MD" "${RAW_OUT_MD}.diag.log" "${RAW_OUT_MD}.exec.log" "$OUT_MD" "${OUT_MD}.diag.log" "${OUT_MD}.exec.log"; do
  if [ -e "$p_chk" ] || [ -L "$p_chk" ]; then
    echo "[ERROR] 输出报告或附属日志路径已存在（为防止覆盖任何工作区内外的待审稿件或既有文件，必须指定全新的不存在路径）: $p_chk" >&2
    exit 2
  fi
  if [ "$p_chk" = "$TASK_MD" ] || [ "$p_chk" = "$SKILL_MD" ] || [ "$p_chk" = "$WORKDIR" ]; then
    echo "[ERROR] 输出报告或附属日志路径不得与送审说明、技能文件或工作目录重合: $p_chk" >&2
    exit 2
  fi
done

TRACKED_FILES_LIST="$(mktemp /tmp/arr_opus_tracked_XXXXXX.lst)"
BEFORE_SNAP="$(mktemp /tmp/arr_opus_before_XXXXXX.sha256)"
AFTER_SNAP="$(mktemp /tmp/arr_opus_after_XXXXXX.sha256)"
MCP_EMPTY="$(mktemp /tmp/arr_opus_mcp_XXXXXX.json)"
OUT_TMP="$(mktemp /tmp/arr_opus_out_XXXXXX.md)"
RUN_LOG="$(mktemp /tmp/arr_opus_log_XXXXXX.log)"
ISOLATED_CFG_DIR="$(mktemp -d /tmp/arr_opus_cfg_XXXXXX)"
RO_STAGE_ROOT="$(mktemp -d /tmp/arr_opus_ro_XXXXXX)"

cleanup() {
  chmod -R u+w "$RO_STAGE_ROOT" 2>/dev/null || true
  rm -rf "$TRACKED_FILES_LIST" "$BEFORE_SNAP" "$AFTER_SNAP" "$MCP_EMPTY" "$OUT_TMP" "$RUN_LOG" "$ISOLATED_CFG_DIR" "$RO_STAGE_ROOT"
}
trap cleanup EXIT

save_diag_log() {
  local diag_path="${OUT_MD}.diag.log"
  if [ ! -e "$diag_path" ] && [ ! -L "$diag_path" ]; then
    (
      set -C
      {
        echo "=== run_opus_c_review diagnostic log ==="
        [ -s "$RUN_LOG" ] && cat "$RUN_LOG"
        [ -s "$OUT_TMP" ] && { echo "--- partial stdout ---"; cat "$OUT_TMP"; }
      } > "$diag_path"
    ) 2>/dev/null || true
    echo "[DIAG] 诊断日志已归档至: $diag_path" >&2
  fi
}

python3 - "$TASK_MD" "$SKILL_MD" "$WORKDIR" "$RAW_OUT_MD" "$TRACKED_FILES_LIST" "${EXTRA_INPUTS[@]}" << 'PY'
import os, pathlib, re, sys

task_md = pathlib.Path(sys.argv[1]).resolve()
skill_md = pathlib.Path(sys.argv[2]).resolve()
workdir = pathlib.Path(sys.argv[3]).resolve()
raw_out_arg = sys.argv[4]
out_md = pathlib.Path(os.path.abspath(raw_out_arg))
out_real = pathlib.Path(os.path.realpath(str(out_md)))
list_out = pathlib.Path(sys.argv[5])
extra_args = [pathlib.Path(os.path.abspath(x)) for x in sys.argv[6:] if x]

out_family_strs = (
    raw_out_arg,
    f"{raw_out_arg}.diag.log",
    f"{raw_out_arg}.exec.log",
    str(out_md),
    f"{out_md}.diag.log",
    f"{out_md}.exec.log",
    str(out_real),
    f"{out_real}.diag.log",
    f"{out_real}.exec.log",
)
for p_chk in out_family_strs:
    if os.path.lexists(p_chk):
        print(f"[ERROR] 输出报告或附属日志路径已存在或为悬空符号链接: {p_chk}", file=sys.stderr)
        sys.exit(2)
out_family = {pathlib.Path(p) for p in out_family_strs}

task_text = task_md.read_text(encoding="utf-8", errors="ignore")
patterns = (
    re.compile(r"\]\(([^)\n]+)\)"),
    re.compile(r"`([^`\n]+)`"),
    re.compile(r"[\"'「『]([^\"'」』\n]+)[\"'」』]"),
    re.compile(r"(?<![A-Za-z0-9_])(?:/[^\s`'\"()[\]{}<>,;:，、。；：！？]+|(?:[^\s`'\"()[\]{}<>,;:，、。；：！？]+/)+[^\s`'\"()[\]{}<>,;:，、。；：！？]+|[^\s`'\"()[\]{}<>,;:，、。；：！？]+\.(?:tex|typ|md|json|csv|bib|py|sh|yaml|yml|txt))"),
)
punct_strip = "`'\"()[]{}<>.,;:，、。；：！？"

candidate_bases = [workdir, task_md.parent, pathlib.Path.cwd().resolve()]
referenced_resolved = set()
for x in extra_args:
    referenced_resolved.add(x)
    referenced_resolved.add(pathlib.Path(os.path.realpath(str(x))))
for pat in patterns:
    for m in pat.finditer(task_text):
        raw = m.group(1) if m.lastindex else m.group(0)
        cleaned = raw.strip().strip(punct_strip).strip()
        cleaned = re.sub(r"(?:#L\d+(?:-L?\d+)?|:\d+(?::\d+)?)$", "", cleaned)
        if not cleaned or cleaned.startswith(("http://", "https://", "mailto:")):
            continue
        p_raw = pathlib.Path(cleaned)
        if p_raw.is_absolute():
            abs_p = pathlib.Path(os.path.abspath(str(p_raw)))
            referenced_resolved.add(abs_p)
            referenced_resolved.add(pathlib.Path(os.path.realpath(str(abs_p))))
        else:
            for base in candidate_bases:
                abs_p = pathlib.Path(os.path.abspath(str(base / p_raw)))
                referenced_resolved.add(abs_p)
                referenced_resolved.add(pathlib.Path(os.path.realpath(str(abs_p))))

if (out_family & referenced_resolved) or (out_family & {task_md, skill_md, workdir}):
    print(f"[ERROR] 输出报告或诊断日志路径与送审说明中引用的待审路径冲突: {out_md}", file=sys.stderr)
    sys.exit(2)

tracked_files = {task_md, skill_md}
for dirpath, _, filenames in os.walk(workdir, followlinks=True):
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

with list_out.open("w", encoding="utf-8") as f:
    for p in sorted(str(x) for x in tracked_files):
        f.write(p + "\n")
PY

CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || true)}"
if [ -z "$CLAUDE_BIN" ] || [ ! -x "$CLAUDE_BIN" ]; then
  echo "[ERROR] 当前环境未找到可执行的 claude CLI，无法直接启动 Claude Opus 5.5 (effort=high) 独立审查。" >&2
  echo "[HINT] 请在具备 claude CLI 的终端执行本脚本，或由用户明确指定替代独立审查载体（严禁作者上下文自审冒充）。" >&2
  exit 3
fi

BWRAP_OK=0
if command -v bwrap >/dev/null 2>&1 && bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp true >/dev/null 2>&1; then
  BWRAP_OK=1
fi

if [ "$BWRAP_OK" -eq 0 ] && [ "${ALLOW_DEGRADED_NO_BWRAP:-0}" != "1" ]; then
  echo "[ERROR] 当前环境缺少可用的 bwrap (bubblewrap) 操作系统只读沙盒，拒绝在无内核级写隔离下启动 Opus 审查。" >&2
  echo "[HINT] 请安装/启用 bwrap，或经用户明确同意仅使用工具白名单+只读副本快照降级隔离后显式设置 ALLOW_DEGRADED_NO_BWRAP=1。" >&2
  exit 3
fi

mkdir -p "$(dirname "$OUT_MD")"

compute_snapshot() {
  local snap_out="$1"
  local ignore_out="${2:-}"
  python3 - "$TRACKED_FILES_LIST" "$WORKDIR" "$snap_out" "$ignore_out" << 'PY'
import hashlib, os, pathlib, sys

list_file = pathlib.Path(sys.argv[1])
workdir = pathlib.Path(sys.argv[2]).resolve()
snap_out = pathlib.Path(sys.argv[3])
ignore_set = set()
if sys.argv[4]:
    for sfx in ("", ".diag.log", ".exec.log"):
        c_ig = pathlib.Path(str(sys.argv[4]) + sfx)
        ignore_set.add(pathlib.Path(os.path.abspath(str(c_ig))))
        ignore_set.add(pathlib.Path(os.path.realpath(str(c_ig))))

files = set()
for line in list_file.read_text(encoding="utf-8").splitlines():
    if line.strip():
        files.add(pathlib.Path(line.strip()))

for dirpath, _, filenames in os.walk(workdir, followlinks=True):
    for fn in filenames:
        raw_fp = pathlib.Path(dirpath) / fn
        fp_abs = pathlib.Path(os.path.abspath(str(raw_fp)))
        fp_real = pathlib.Path(os.path.realpath(str(raw_fp)))
        if fp_abs in ignore_set or fp_real in ignore_set:
            continue
        files.add(fp_real if raw_fp.exists() else fp_abs)

rows = []
for fp in sorted(files, key=lambda x: str(x)):
    if pathlib.Path(os.path.abspath(str(fp))) in ignore_set or pathlib.Path(os.path.realpath(str(fp))) in ignore_set:
        continue
    if not fp.exists():
        rows.append(f"MISSING  {fp}")
    elif fp.is_file():
        h = hashlib.sha256(fp.read_bytes()).hexdigest()
        rows.append(f"{h}  {fp}")
snap_out.write_text("\n".join(rows) + "\n", encoding="utf-8")
PY
}

compute_snapshot "$BEFORE_SNAP" ""

printf '{"mcpServers":{}}\n' > "$MCP_EMPTY"
ISOLATED_SETTINGS="$ISOLATED_CFG_DIR/settings.json"
cat > "$ISOLATED_SETTINGS" << 'EOF'
{
  "disableAllHooks": true,
  "permissions": {
    "defaultMode": "plan",
    "allow": ["Read", "Grep", "Glob"],
    "deny": ["Bash", "Edit", "Write", "MultiEdit", "NotebookEdit"]
  }
}
EOF

RO_WORKDIR="$RO_STAGE_ROOT/workspace"
python3 -c 'import shutil, sys; shutil.copytree(sys.argv[1], sys.argv[2], symlinks=False, dirs_exist_ok=True)' "$WORKDIR" "$RO_WORKDIR"
chmod -R a-w "$RO_WORKDIR"

PROMPT="你是独立批判者 c（顶会论文审稿人，执行 arr-paper-reviewer 前三关审查）。请严格遵照以下完整《arr-paper-reviewer 技能规范》与《本次送审说明》，只读检查本工作区与送审说明中的文件，严禁修改任何待审文件。
执行约束：所有文件一律按 UTF-8 编码读取（Python 环境已启用 PYTHONUTF8=1，严禁用 python - 从标准输入阻塞读取脚本）；严禁启动或继续委派任何子代理（Subagents）；严禁读取 ~/.kaggle 等无关敏感目录；严禁执行任何 Git 写操作或文件修改（提交由外部脚本负责）。
报告必须包含『一、』『二、』『三、』『四、』『五、』五个完整章节标题及各自实质审查正文（第一节含宣称核对表，第二节含混淆矩阵表，第五节含 Soundness/Excitement/Overall Assessment/Reviewer Confidence 四项评分），且全文最后一个非空行必须严格独占一行输出『**总体判定：无阻断**』或『**总体判定：有阻断**』（不得增减星号或附加标点）。

==================== 《arr-paper-reviewer 技能规范》 ====================
$(cat "$SKILL_MD")

==================== 《本次送审说明》 ====================
$(cat "$TASK_MD")"

CLAUDE_ARGS=(
  -p "$PROMPT"
  --bare
  --setting-sources ""
  --settings "$ISOLATED_SETTINGS"
  --permission-mode plan
  --model "$MODEL"
  --effort "$EFFORT"
  --tools "Read,Grep,Glob"
  --allowedTools "Read,Grep,Glob"
  --disallowedTools "Bash,Edit,Write,MultiEdit,NotebookEdit"
  --strict-mcp-config
  --mcp-config "$MCP_EMPTY"
  --no-session-persistence
)

# 若受保护输入位于 /tmp 下，在 --tmpfs /tmp 之后将其按原路径只读挂载回沙盒内，防止被遮蔽
BWRAP_TMP_BINDS=()
while IFS= read -r tracked_p; do
  case "$tracked_p" in
    /tmp/*)
      if [ -e "$tracked_p" ]; then
        BWRAP_TMP_BINDS+=(--ro-bind "$tracked_p" "$tracked_p")
      fi
      ;;
  esac
done < "$TRACKED_FILES_LIST"

export PYTHONUTF8=1
set +e
if [ "$BWRAP_OK" -eq 1 ]; then
  CLAUDE_CONFIG_DIR="$ISOLATED_CFG_DIR" bwrap \
    --ro-bind / / \
    --dev /dev \
    --proc /proc \
    --tmpfs /tmp \
    "${BWRAP_TMP_BINDS[@]}" \
    --bind "$ISOLATED_CFG_DIR" "$ISOLATED_CFG_DIR" \
    --ro-bind "$MCP_EMPTY" "$MCP_EMPTY" \
    --ro-bind "$RO_WORKDIR" "$WORKDIR" \
    --chdir "$WORKDIR" \
    "$CLAUDE_BIN" "${CLAUDE_ARGS[@]}" < /dev/null > "$OUT_TMP" 2> "$RUN_LOG"
  CLI_RC=$?
else
  (
    cd "$RO_WORKDIR"
    CLAUDE_CONFIG_DIR="$ISOLATED_CFG_DIR" "$CLAUDE_BIN" "${CLAUDE_ARGS[@]}" < /dev/null > "$OUT_TMP" 2> "$RUN_LOG"
  )
  CLI_RC=$?
fi
set -e

compute_snapshot "$AFTER_SNAP" ""
if ! diff -u "$BEFORE_SNAP" "$AFTER_SNAP" >/dev/null; then
  echo "[ERROR] 只读审查铁律被违反！审查期间以下受保护文件发生变更：" >&2
  diff -u "$BEFORE_SNAP" "$AFTER_SNAP" >&2 || true
  save_diag_log
  exit 5
fi

if [ "$CLI_RC" -ne 0 ]; then
  echo "[ERROR] claude CLI 非零退出 (exit=$CLI_RC)，拒绝验收报告：" >&2
  cat "$RUN_LOG" >&2 || true
  save_diag_log
  exit 4
fi

if grep -Eiq "failed to spawn|Provided authentication token is expired|Your access token could not be refreshed" "$RUN_LOG" "$OUT_TMP" 2>/dev/null; then
  echo "[ERROR] CLI 启动或鉴权失败，拒绝验收报告：" >&2
  cat "$RUN_LOG" >&2 || true
  save_diag_log
  exit 4
fi

if [ ! -s "$OUT_TMP" ]; then
  echo "[ERROR] 审查输出为空。" >&2
  cat "$RUN_LOG" >&2 || true
  save_diag_log
  exit 4
fi

run_arr_validator() {
  local target_md="$1"
  local req_pass="${2:-0}"
  local precheck_py="$SCRIPT_DIR/../../conference-submission-auditor/scripts/submission_precheck.py"
  if [ -f "$precheck_py" ]; then
    if [ "$req_pass" = "1" ]; then
      python3 "$precheck_py" --check-verdict "$target_md" --report-type arr --workdir "$WORKDIR" --require-pass
    else
      python3 "$precheck_py" --check-verdict "$target_md" --report-type arr --workdir "$WORKDIR"
    fi
  else
    python3 - "$target_md" "$req_pass" << 'PY'
from decimal import Decimal, InvalidOperation
import json, pathlib, re, sys

EXACT_VERDICTS = {"**总体判定：无阻断**": "无阻断", "**总体判定：有阻断**": "有阻断"}
LOOSE_RE = re.compile(r"总体判定\s*[：:]\s*(无阻断|有阻断)")
INLINE_CODE_RE = re.compile(r"`[^`]+`")
FENCE_RE = re.compile(r"^\s*(`{3,}|~{3,})")
CRASH_PATS = (
    re.compile(r"(?i)failed\s+to\s+spawn\s+code-mode\s+host"),
    re.compile(r"(?i)bubblewrap\s+is\s+unavailable"),
    re.compile(r"(?i)provided\s+authentication\s+token\s+is\s+expired|token_expired"),
    re.compile(r"(?i)your\s+access\s+token\s+could\s+not\s+be\s+refreshed"),
    re.compile(r"^\[ERROR\]"),
    re.compile(r"^Traceback \(most recent call last\):"),
)
TARGET_DEFECT_RE = re.compile(
    r"(?:待审|被审|被测|所审|目标|作者的?|文中的?|稿件中的?|现有的?)?"
    r"(?:解析器|脚本|代码|程序|函数|模块|实现|系统|模型|算法|方法|流水线|接口|工具|正则|校验器)\s*$"
    r"|\[(?:Blocker|Major|Minor|Question)[^\]]*\]",
    re.IGNORECASE,
)
UNEXEC_PATS = (
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
BLOCKER_TAG_RE = re.compile(r"\[Blocker(?:\s*阻断)?\]", re.IGNORECASE)
CLAUSE_SEP_RE = re.compile(r"[；;。！!？?|\n，,]")
NEG_PRE_RE = re.compile(
    r"(?:(?:无|未发现|未见|没有|不存在|零\s*(?:项|个|处)?)|(?<![\d.])0(?![\d.])\s*(?:项|个|处)?|(?<![A-Za-z])(?:no|zero|none|without)\b)"
    r"\s*(?:\*\*|`)*\s*$",
    re.IGNORECASE,
)
NEG_SUF_RE = re.compile(
    r"^\s*(?:\*\*|`)*\s*(?:[：:]\s*)?(?:无|(?<![\d.])0(?![\d.])\s*(?:项|个|处)?|零\s*(?:项|个|处)?|None\b|N/A\b)(?:\s*$|\s*[。；;，,|])",
    re.IGNORECASE,
)
BLOCKER_CNT_RE = re.compile(r"(?<![未无\u7121])(?:发现|共|有|存在)\s*(?:\*\*|`)*\s*[1-9]\d*\s*项[^\n。；;]*?(?:阻断|\[Blocker)")
ARR_SEC1_POS = re.compile(r"(?:宣称|闭合|核对|映射|证据|过度宣称|缺口|claim)", re.IGNORECASE)
ARR_SEC2_POS = re.compile(r"(?:混淆|替代解释|消融|CoT|API|ROC-AUC|confound|ablation|不适用)", re.IGNORECASE)
ARR_SEC3_POS = re.compile(r"(?:lit_kb|kb|知识库|竞品|基线|文献|baseline|Related\s+Work)", re.IGNORECASE)
TABLE_SEP_RE = re.compile(r"^\s*\|?(?:\s*:?-{2,}:?\s*\|)+\s*:?-{2,}:?\s*\|?\s*$")
STUB_SECTION_BODY_RE = re.compile(
    r"^(?:[-*+]\s*)?(?:略|从略|同上|待补|待补充|待填|暂无|无内容|N/?A|TBD|TODO|none)\.?\s*$",
    re.IGNORECASE,
)
SCORE_PATS = (
    re.compile(r"(?i)\bSoundness\b[^\n\d+-]{0,25}([+-]?\d+(?:\.\d+)?)(?:\s*/\s*([+-]?\d+(?:\.\d+)?))?"),
    re.compile(r"(?i)\bExcitement\b[^\n\d+-]{0,25}([+-]?\d+(?:\.\d+)?)(?:\s*/\s*([+-]?\d+(?:\.\d+)?))?"),
    re.compile(r"(?i)\bOverall(?:\s+Assessment)?\b[^\n\d+-]{0,25}([+-]?\d+(?:\.\d+)?)(?:\s*/\s*([+-]?\d+(?:\.\d+)?))?"),
    re.compile(r"(?i)\b(?:Reviewer\s+)?Confidence\b[^\n\d+-]{0,25}([+-]?\d+(?:\.\d+)?)(?:\s*/\s*([+-]?\d+(?:\.\d+)?))?"),
)
REQUIRED = ("一、", "二、", "三、", "四、", "五、")

def has_active_blocker(line: str) -> bool:
    unwrapped = line.replace("`", "").replace("*", "")
    if BLOCKER_CNT_RE.search(unwrapped):
        return True
    for m in BLOCKER_TAG_RE.finditer(unwrapped):
        pre = CLAUSE_SEP_RE.split(unwrapped[:m.start()])[-1]
        suf = unwrapped[m.end():]
        if NEG_PRE_RE.search(pre) or NEG_SUF_RE.search(suf):
            continue
        return True
    return False

def is_unexecuted(line: str) -> bool:
    s = INLINE_CODE_RE.sub("", line)
    for pat in UNEXEC_PATS:
        for m in pat.finditer(s):
            if TARGET_DEFECT_RE.search(s[:m.start()]):
                continue
            return True
    return False

def has_table_row(text: str) -> bool:
    seen_header = False
    seen_sep = False
    for raw in text.splitlines():
        ln = raw.strip()
        if "|" not in ln:
            seen_header = False
            seen_sep = False
            continue
        if TABLE_SEP_RE.match(ln):
            if seen_header:
                seen_sep = True
            continue
        if len([c.strip() for c in ln.strip("|").split("|") if c.strip()]) >= 3:
            if not seen_sep:
                seen_header = True
            else:
                return True
    return False

path = pathlib.Path(sys.argv[1])
req_pass = sys.argv[2] == "1"
raw_lines = path.read_text(encoding="utf-8").splitlines()
non_empty_all = [ln.strip() for ln in raw_lines if ln.strip()]
if not non_empty_all:
    sys.exit(2)

items = []
fence = None
for ln in raw_lines:
    m = FENCE_RE.match(ln)
    if m:
        mk = m.group(1)
        if fence is None:
            fence = mk
            continue
        if mk[0] == fence[0] and len(mk) >= len(fence):
            fence = None
            continue
    if ln.strip():
        items.append((ln.strip(), fence is not None))

outside = [ln for ln, in_f in items if not in_f]
if fence is not None or not outside or non_empty_all[-1] != outside[-1]:
    sys.exit(2)
last = outside[-1]
if last not in EXACT_VERDICTS or len(outside) < 2:
    sys.exit(2)
verdict = EXACT_VERDICTS[last]
body_items = items[:-1]
for ln, in_f in body_items:
    ln_no_code = INLINE_CODE_RE.sub("", ln)
    if any(p.search(ln_no_code) for p in CRASH_PATS):
        sys.exit(2)
    if not in_f and is_unexecuted(ln):
        sys.exit(2)
    if verdict == "无阻断":
        if has_active_blocker(ln):
            sys.exit(2)
    if not in_f and LOOSE_RE.search(ln_no_code):
        if ln not in EXACT_VERDICTS or EXACT_VERDICTS[ln] != verdict:
            sys.exit(2)

sec_pats = [(s, re.compile(rf"^(?:#+\s*|\d+\.\s*|\*\*\s*)?{re.escape(s)}\S+")) for s in REQUIRED]
idxs = []
pos = 0
for s, pat in sec_pats:
    found = -1
    for i in range(pos, len(body_items)):
        ln, in_f = body_items[i]
        if not in_f and pat.match(ln) and not any(o != s and o in ln for o in REQUIRED):
            found = i
            break
    if found == -1:
        sys.exit(2)
    idxs.append(found)
    pos = found + 1
bounds = idxs + [len(body_items)]
sec_bodies = {}
for k, s in enumerate(REQUIRED):
    sub = [ln for ln, in_f in body_items[bounds[k]+1:bounds[k+1]] if in_f or (not ln.startswith("#") and not any(p.match(ln) for _, p in sec_pats))]
    if not sub:
        sys.exit(2)
    joined_sub = "\n".join(sub).strip()
    if STUB_SECTION_BODY_RE.match(joined_sub) or len(joined_sub) < 6:
        sys.exit(2)
    sec_bodies[s] = joined_sub

for sp in SCORE_PATS:
    m = sp.search(sec_bodies["五、"])
    if not m:
        sys.exit(2)
    try:
        val = Decimal(m.group(1))
        den = Decimal(m.group(2)) if m.group(2) is not None else Decimal("5")
    except InvalidOperation:
        sys.exit(2)
    if not (Decimal("1") <= val <= Decimal("5")) or den != Decimal("5"):
        sys.exit(2)

if not (ARR_SEC1_POS.search(sec_bodies["一、"]) and has_table_row(sec_bodies["一、"])):
    sys.exit(2)
if not (ARR_SEC2_POS.search(sec_bodies["二、"]) and has_table_row(sec_bodies["二、"])):
    sys.exit(2)
if not ARR_SEC3_POS.search(sec_bodies["三、"]):
    sys.exit(2)

print(json.dumps({"file": str(path), "report_type": "arr", "valid_report": True, "approved_no_blockers": verdict == "无阻断", "detail": verdict}, ensure_ascii=False))
if req_pass and verdict != "无阻断":
    sys.exit(1)
PY
  fi
}

set +e
run_arr_validator "$OUT_TMP" "0"
VAL_RC=$?
set -e

if [ "$VAL_RC" -ne 0 ]; then
  echo "[ERROR] 审查报告未通过结构与完整性校验 (exit=$VAL_RC)。" >&2
  save_diag_log
  exit 2
fi

(set -C; cat "$OUT_TMP" > "$OUT_MD")

compute_snapshot "$AFTER_SNAP" "$OUT_MD"
if ! diff -u "$BEFORE_SNAP" "$AFTER_SNAP" >/dev/null; then
  echo "[ERROR] 只读审查铁律被违反！写入报告后复核发现受保护文件发生变更：" >&2
  diff -u "$BEFORE_SNAP" "$AFTER_SNAP" >&2 || true
  exit 5
fi

if [ "${REQUIRE_NO_BLOCKERS:-0}" = "1" ]; then
  run_arr_validator "$OUT_MD" "1" >/dev/null
fi
