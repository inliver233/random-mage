---
description: 基于 Issue CSV 执行闭环（实现→验收→提交→回归）
argument-hint: "<issues CSV 文件路径>"
---

你现在处于「Issues CSV 执行模式（闭环）」。

目标：以 `issues/*.csv` 为任务边界与状态源，推进并交付 Issue 的完整闭环：**实现 → 验收 → 本地提交 + push → 回归**。

> 说明：本 prompt 只在用户显式调用 `/prompts:issues_csv_execute` 时生效，不影响普通对话。

## 0) 先读（项目约束）
- 执行约束（分支/提交/测试）：`AGENTS.md`
- CSV 字段规则（表头/必填/枚举）：`issues/README.md`
- 测试策略：`docs/testing-policy.md`
- E2E 黑盒测试说明：`test/README.md`、`test/ADDING_TESTS.md`

## 1) 总体规则（必须遵守）

1. **CSV 是边界与状态源**：只做 CSV 这一行描述的工作；任何需求变更先写回 CSV（`Description/Acceptance/Test_Method/Tools/Files/Dependencies/Notes`），再改代码。
2. **默认目标是完成整个 CSV**：顺序由你决定（优先高价值/解阻塞/减少上下文切换），但最终要把 CSV 里的 issues 推到 DONE。
3. **闭环不可缺省**：实现 + 验收（按 `Test_Method`） + 本地 git commit（并按约定 push）缺一不可（回归可在批次末统一做）。
4. **状态驱动（枚举值固定）**：
   - `Dev_Status` / `Review1_Status` / `Regression_Status`：`TODO | DOING | DONE`
5. **每条 Issue = 一个 commit**：同一 commit 必须包含：代码变更 + 当前 CSV 文件状态更新。
6. **多步任务（≥2 步）必须用 `update_plan`**：状态需实时推进 `pending → in_progress → completed`（不要批量更新）。
7. **不假想结果，但允许“受限验收”**：若环境/依赖导致 `Test_Method` 无法运行，允许继续提交，但必须在该行 `Notes` 记录：
   - `validation_limited:<原因>`
   - `manual_test:<后续可执行命令/步骤>`
   - `evidence:<已完成的替代验证>`
   - `risk:<low|medium|high> <说明>`
   并在交接输出中明确“未运行哪些测试/为何未运行”。
8. **Windows 编码注意**：读取源码优先用 `rg -n`；若用 PowerShell 查看文件，推荐 `Get-Content -Encoding UTF8`（避免 UTF-8 无 BOM 被误解码导致“乱码/误判”）。
9. **Review 类 issues 的证据落盘**：若该行属于“审计/评审”任务（不一定改代码），仍需产出可追溯输出（推荐：`docs/reviews/<ID>.md`）并与 CSV 状态一并提交（同一 commit）。

## 2) Git 分支规则（核心约束）
- **所有代码变更与 git commit 必须在 `test`（或 `test/*`）分支进行**。
- 禁止在 `dev` / `main` 分支直接提交或更新。
- 执行任何 git 操作前必须检查分支：

```bash
git branch --show-current
```

不在 `test` 时：

```bash
git checkout test
```

## 3) 执行流程（每条 Issue 必须按顺序走）

对 CSV 的某一行（一个 Issue），按以下步骤闭环：

1. **选题**
   - 选择 `Dev_Status=TODO` 的一行；读取 `Title/Description/Acceptance/Test_Method/Files/Dependencies/Notes`。
   - 若有 `Dependencies` 未满足：在 `Notes` 写 `blocked:<原因>`，跳到下一条。
2. **进入 DOING（先改 CSV 再改代码）**
   - 将该行 `Dev_Status=DOING` 并保存 CSV。
   - 可选（推荐）：先跑一次 CSV 校验脚本，避免后续提交时才发现表头/枚举错误：
     - `python .codex/skills/plan/scripts/validate_issues_csv.py <issues.csv>`
3. **上下文收集（最小必要）**
   - 优先从 `Files` / `Notes.refs` 指向的路径切入；用 `rg` 精确定位；避免目录级扫。
4. **实现（只做本 Issue）**
   - 严格遵循 `Description` 的边界；任何范围扩大先回写 CSV 再继续。
5. **验收（按 Test_Method）**
   - 运行 `Test_Method` 指定的命令或按其 manual 步骤验证。
   - 通过：把关键输出/证据摘要写进 `Notes`（例如 trace 路径、截图路径、关键日志片段）。
6. **Review1（自查/复查）**
   - 通过后将该行 `Review1_Status=DONE`。
7. **完成开发状态**
   - 将该行 `Dev_Status=DONE`。
   - `Regression_Status`：默认保持 `TODO`，等整个 CSV 全部完成后再统一跑回归并批量置 `DONE`。
8. **Git 提交（闭环关键步骤）**
   - 再次确认当前分支为 `test`（或 `test/*`）。
   - `git status` / `git diff` 确认改动只覆盖本 Issue。
   - `git add` 必须包含：代码变更 + 当前 CSV 文件。
   - Commit message 格式：`[<ID>] <Title>`
9. **Push 到远端（用户要求：每次提交后 push）**
   - 若尚未设置 upstream：`git push -u origin test`
   - 否则：`git push`
10. **落盘记录**
   - 在该行 `Notes` 追加：`done_at:<YYYY-MM-DD>`、（可选）`git:<short-sha>`、受限验收信息（如有）。

## 4) 回归（批次末统一做）
- 当 CSV 所有行 `Dev_Status=DONE` 后，运行回归（优先用一键脚本）：

```powershell
pwsh test/run-all.ps1
```

- 回归通过后，将所有行 `Regression_Status=DONE` 并提交一次“meta commit”（只改 CSV）。
- 若回归无法运行：按“受限验收”写明原因与风险，**不得**声称回归通过。

## 5) 交接输出（必须包含）
- 本次处理的 `ID/Title`
- 关键变更点与文件引用（`path:line`）
- 实际运行的测试/结果（或受限验收记录）
- 本地 commit hash（如已提交）+ 已 push 情况
- 风险与下一步建议
