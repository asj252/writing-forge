#!/usr/bin/env bash
# 顶会论文提交审计员（后三关 conference-submission-auditor）独立批判者 c 派发脚本
# 强制绑定载体：Codex CLI (gpt-6.1-sol, model_reasoning_effort=high, 只读模式)
# 用法：bash run_codex_submission_audit.sh <送审任务说明_TASK.md> <输出报告_REVIEW.md> [工作目录] [额外受保护输入路径...]
# 退出码：
#   0 = 审计报告生成且结构校验通过（若设置 REQUIRE_NO_BLOCKERS=1，则仅在末行判定为『无阻断』时返回 0）
#   1 = 已设置 REQUIRE_NO_BLOCKERS=1，报告结构有效但末行判定为『有阻断』
#   2 = 参数错误、输出路径冲突或报告未通过完整性校验
#   3 = 未找到可执行的 codex CLI 或缺少操作系统只读沙盒 bwrap（未显式授权降级）
#   4 = CLI 执行失败、沙盒或鉴权异常（诊断日志保存至 <output_review_md_path>.diag.log）
#   5 = 只读铁律被违反（前后 SHA-256 快照不一致）

set -euo pipefail

if [ "$#" -lt 2 ]; then
  echo "用法: $0 <task_md_path> <output_review_md_path> [workdir] [extra_protected_paths...]" >&2
  exit 2
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SKILL_MD="$(realpath "$SCRIPT_DIR/../SKILL.md")"
PRECHECK_PY="$(realpath "$SCRIPT_DIR/submission_precheck.py")"
TASK_MD="$(realpath "$1")"
RAW_OUT_MD="$2"
OUT_MD="$(realpath -m "$RAW_OUT_MD")"
WORKDIR="$(realpath "${3:-$(pwd)}")"
EXTRA_INPUTS=("${@:4}")

EXPECTED_MODEL="gpt-6.1-sol"
EXPECTED_EFFORT="high"
MODEL="${CODEX_MODEL:-$EXPECTED_MODEL}"
EFFORT="${CODEX_EFFORT:-$EXPECTED_EFFORT}"

if [ "$MODEL" != "$EXPECTED_MODEL" ] || [ "$EFFORT" != "$EXPECTED_EFFORT" ]; then
  echo "[ERROR] 严禁静默降级或替换模型/推理强度：仅允许 MODEL=$EXPECTED_MODEL 且 EFFORT=$EXPECTED_EFFORT（当前请求: MODEL=$MODEL, EFFORT=$EFFORT）。" >&2
  exit 2
fi

if [ ! -s "$SKILL_MD" ]; then
  echo "[ERROR] 找不到技能规则文件: $SKILL_MD" >&2
  exit 2
fi

if [ ! -f "$PRECHECK_PY" ]; then
  echo "[ERROR] 找不到预检与报告校验脚本: $PRECHECK_PY" >&2
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

for cand_out in "$RAW_OUT_MD" "$OUT_MD" "${RAW_OUT_MD}.diag.log" "${OUT_MD}.diag.log" "${RAW_OUT_MD}.exec.log" "${OUT_MD}.exec.log"; do
  if [ -e "$cand_out" ] || [ -L "$cand_out" ]; then
    echo "[ERROR] 输出报告或附属日志路径已存在（为防止覆盖任何工作区内外的待审稿件或既有文件，必须指定全新的不存在路径）: $cand_out" >&2
    exit 2
  fi
done

if [ "$OUT_MD" = "$TASK_MD" ] || [ "$OUT_MD" = "$SKILL_MD" ] || [ "$OUT_MD" = "$PRECHECK_PY" ] || [ "$OUT_MD" = "$WORKDIR" ]; then
  echo "[ERROR] 输出报告路径不得与送审说明、技能规则、预检脚本或工作目录重合: $OUT_MD" >&2
  exit 2
fi

TRACKED_FILES_LIST="$(mktemp /tmp/csa_tracked_XXXXXX.lst)"
PROMPT_TMP="$(mktemp /tmp/csa_task_XXXXXX.md)"
BEFORE_SNAP="$(mktemp /tmp/csa_before_XXXXXX.sha256)"
AFTER_SNAP="$(mktemp /tmp/csa_after_XXXXXX.sha256)"
OUT_TMP="$(mktemp /tmp/csa_out_XXXXXX.md)"
RUN_LOG="$(mktemp /tmp/csa_log_XXXXXX.log)"
RO_STAGE_ROOT="$(mktemp -d /tmp/csa_ro_XXXXXX)"

cleanup() {
  chmod -R u+w "$RO_STAGE_ROOT" 2>/dev/null || true
  rm -rf "$TRACKED_FILES_LIST" "$PROMPT_TMP" "$BEFORE_SNAP" "$AFTER_SNAP" "$OUT_TMP" "$RUN_LOG" "$RO_STAGE_ROOT"
}
trap cleanup EXIT

save_diag_log() {
  local diag_path="${OUT_MD}.diag.log"
  if [ ! -e "$diag_path" ] && [ ! -L "$diag_path" ]; then
    (
      set -C
      {
        echo "=== run_codex_submission_audit diagnostic log ==="
        [ -s "$RUN_LOG" ] && cat "$RUN_LOG"
        [ -s "$OUT_TMP" ] && { echo "--- partial output ---"; cat "$OUT_TMP"; }
      } > "$diag_path"
    ) 2>/dev/null || true
    echo "[DIAG] 诊断日志已归档至: $diag_path" >&2
  fi
}

python3 "$PRECHECK_PY" \
  --collect-protected "$TASK_MD" "$WORKDIR" "$RAW_OUT_MD" "$TRACKED_FILES_LIST" \
  --extra-protected "$SKILL_MD" "$PRECHECK_PY" "${EXTRA_INPUTS[@]}"

CODEX_BIN="${CODEX_BIN:-$(command -v codex || true)}"
if [ -z "$CODEX_BIN" ] && [ -x "$HOME/.local/bin/codex" ]; then
  CODEX_BIN="$HOME/.local/bin/codex"
fi
if [ -z "$CODEX_BIN" ] || [ ! -x "$CODEX_BIN" ]; then
  echo "[ERROR] 当前环境未找到可执行的 codex CLI，无法启动 Codex (gpt-6.1-sol, high) 独立审计。" >&2
  exit 3
fi

BWRAP_OK=0
if command -v bwrap >/dev/null 2>&1 && bwrap --ro-bind / / --dev /dev --proc /proc --tmpfs /tmp true >/dev/null 2>&1; then
  BWRAP_OK=1
fi

if [ "$BWRAP_OK" -eq 0 ] && [ "${ALLOW_DEGRADED_NO_BWRAP:-0}" != "1" ]; then
  echo "[ERROR] 当前环境缺少可用的 bwrap (bubblewrap) 操作系统只读沙盒，Codex -s read-only 无法启动子命令，拒绝静默降级。" >&2
  echo "[HINT] 请安装/启用 bwrap，或经用户明确知情同意后显式设置 ALLOW_DEGRADED_NO_BWRAP=1（启用 chmod -R a-w 只读副本工作区 + 前后全量 SHA-256 快照比对模式）。" >&2
  exit 3
fi

mkdir -p "$(dirname "$OUT_MD")"

python3 "$PRECHECK_PY" --snapshot "$TRACKED_FILES_LIST" "$WORKDIR" "$BEFORE_SNAP"

RO_WORKDIR="$RO_STAGE_ROOT/workspace"
OUT_STAGE_DIR="$RO_STAGE_ROOT/out"
CODEX_STAGE_HOME="$RO_STAGE_ROOT/home"
mkdir -p "$OUT_STAGE_DIR" "$CODEX_STAGE_HOME"
if [ -d "${HOME:-}/.codex" ]; then
  python3 -c 'import shutil, sys; shutil.copytree(sys.argv[1], sys.argv[2], symlinks=False, dirs_exist_ok=True)' "$HOME/.codex" "$CODEX_STAGE_HOME/.codex"
fi
python3 -c 'import shutil, sys; shutil.copytree(sys.argv[1], sys.argv[2], symlinks=False, dirs_exist_ok=True)' "$WORKDIR" "$RO_WORKDIR"
chmod -R a-w "$RO_WORKDIR"

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

cat > "$PROMPT_TMP" << EOF
你是独立批判者 c（顶会论文提交审计员，执行 conference-submission-auditor 后三关硬核审计）。
请严格遵照以下完整《conference-submission-auditor 技能规范》与《本次送审说明》，在只读模式下运行检查脚本（$PRECHECK_PY）并执行只读 Python 命令（严禁用 python - 从 stdin 阻塞读取）复算核对所有表格数字，严禁修改任何待审文件。
执行约束：所有文件一律按 UTF-8 编码读取（Python 环境已设 PYTHONUTF8=1）；严禁启动或继续委派任何子代理（Subagents）；严禁读取 ~/.kaggle 等无关敏感目录；严禁执行任何 Git 写操作或文件修改（提交由外部派发脚本负责）。
报告必须包含『一、』『二、』『三、』『四、』四个完整章节标题及各自实质审计正文（其中『一、』必须记录实际已执行的对账命令及包含『稿件数值 | 原件数值 | 差值 | 状态（PASS / MISMATCH）』的逐格核对表；差值列统一定义为『稿件数值 - 原件数值』或非负绝对差值『|稿件数值 - 原件数值|』），且全文最后一个非空行必须严格独占一行输出『**总体判定：无阻断**』或『**总体判定：有阻断**』（不得增减星号或附加标点）。

==================== 《conference-submission-auditor 技能规范》 ====================
$(cat "$SKILL_MD")

==================== 《本次送审说明》 ====================
$(cat "$TASK_MD")
EOF

export PYTHONUTF8=1
set +e
if [ "$BWRAP_OK" -eq 1 ]; then
  HOME="$CODEX_STAGE_HOME" bwrap \
    --ro-bind / / \
    --dev /dev \
    --proc /proc \
    --tmpfs /tmp \
    "${BWRAP_TMP_BINDS[@]}" \
    --bind "$CODEX_STAGE_HOME" "$CODEX_STAGE_HOME" \
    --bind "$OUT_STAGE_DIR" "$OUT_STAGE_DIR" \
    --ro-bind "$RO_WORKDIR" "$WORKDIR" \
    --chdir "$WORKDIR" \
    "$CODEX_BIN" exec \
      -s read-only \
      --ephemeral \
      --skip-git-repo-check \
      -m "$MODEL" \
      -c model_reasoning_effort="\"$EFFORT\"" \
      -C "$WORKDIR" \
      -o "$OUT_STAGE_DIR/report.md" \
      -- "$(cat "$PROMPT_TMP")" < /dev/null > "$RUN_LOG" 2>&1
  CLI_RC=$?
  [ -f "$OUT_STAGE_DIR/report.md" ] && cp "$OUT_STAGE_DIR/report.md" "$OUT_TMP"
else
  "$CODEX_BIN" exec \
    -s danger-full-access \
    --ephemeral \
    --skip-git-repo-check \
    -m "$MODEL" \
    -c model_reasoning_effort="\"$EFFORT\"" \
    -C "$RO_WORKDIR" \
    -o "$OUT_TMP" \
    -- "$(cat "$PROMPT_TMP")" < /dev/null > "$RUN_LOG" 2>&1
  CLI_RC=$?
fi
set -e

python3 "$PRECHECK_PY" --snapshot "$TRACKED_FILES_LIST" "$WORKDIR" "$AFTER_SNAP"
if ! diff -u "$BEFORE_SNAP" "$AFTER_SNAP" >/dev/null; then
  echo "[ERROR] 只读审计铁律被违反！审计期间以下受保护文件发生变更：" >&2
  diff -u "$BEFORE_SNAP" "$AFTER_SNAP" >&2 || true
  save_diag_log
  exit 5
fi

if [ "$CLI_RC" -ne 0 ]; then
  echo "[ERROR] Codex CLI 非零退出 (exit=$CLI_RC)，拒绝验收报告：" >&2
  cat "$RUN_LOG" >&2 || true
  save_diag_log
  exit 4
fi

if grep -Eiq '(^|[^"'"'"'])failed to spawn code-mode host|(^|[^"'"'"'])bubblewrap is unavailable|(^|[^"'"'"'])Provided authentication token is expired|(^|[^"'"'"'])Your access token could not be refreshed' "$RUN_LOG" "$OUT_TMP" 2>/dev/null; then
  echo "[ERROR] Codex 启动、沙盒或鉴权失败，拒绝验收报告：" >&2
  cat "$RUN_LOG" >&2 || true
  save_diag_log
  exit 4
fi

if [ ! -s "$OUT_TMP" ]; then
  echo "[ERROR] Codex 未生成非空审计报告。" >&2
  cat "$RUN_LOG" >&2 || true
  save_diag_log
  exit 4
fi

if ! python3 "$PRECHECK_PY" --verify-exec-log "$RUN_LOG" "$PROMPT_TMP"; then
  echo "[ERROR] 运行日志中未发现剥离提示词回显后的真实命令执行记录，拒绝验收纯静态阅读报告。" >&2
  save_diag_log
  exit 2
fi

set +e
python3 "$PRECHECK_PY" --check-verdict "$OUT_TMP" --report-type auditor --workdir "$WORKDIR" --task-md "$TASK_MD"
VAL_RC=$?
set -e

if [ "$VAL_RC" -ne 0 ]; then
  echo "[ERROR] 审计报告未通过结构与完整性校验 (exit=$VAL_RC)。" >&2
  save_diag_log
  exit 2
fi

(set -C; cat "$OUT_TMP" > "$OUT_MD")
if [ "${SAVE_EXEC_LOG:-0}" = "1" ]; then
  EXEC_LOG_OUT="${OUT_MD}.exec.log"
  if [ -e "$EXEC_LOG_OUT" ] || [ -L "$EXEC_LOG_OUT" ]; then
    echo "[ERROR] 执行日志输出路径已存在，拒绝覆盖: $EXEC_LOG_OUT" >&2
    exit 2
  fi
  (set -C; cat "$RUN_LOG" > "$EXEC_LOG_OUT")
fi

python3 "$PRECHECK_PY" --snapshot "$TRACKED_FILES_LIST" "$WORKDIR" "$AFTER_SNAP" --ignore-out "$OUT_MD"
if ! diff -u "$BEFORE_SNAP" "$AFTER_SNAP" >/dev/null; then
  echo "[ERROR] 只读审计铁律被违反！写入报告后复核发现受保护文件发生变更：" >&2
  diff -u "$BEFORE_SNAP" "$AFTER_SNAP" >&2 || true
  exit 5
fi

if [ "${REQUIRE_NO_BLOCKERS:-0}" = "1" ]; then
  python3 "$PRECHECK_PY" --check-verdict "$OUT_MD" --report-type auditor --workdir "$WORKDIR" --task-md "$TASK_MD" --require-pass >/dev/null
fi
