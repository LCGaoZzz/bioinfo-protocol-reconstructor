# Bioinformatics Protocol Reconstructor

**Traceable paper → figure → Methods → code → result reconstruction and audit for bioinformatics papers.**

从论文正文、图版、Methods/补充材料、活跃代码与参数、运行时证据到生物学解释，把一篇生物信息学论文的分析流程重建为**可追溯、可审计、可复现**的证据链。产出不是一份摘要，而是一个证据包（evidence package）：每一行分析都把「论文主张 ↔ 图/面板 ↔ 方法与参数 ↔ 代码位置 ↔ 输入/输出 ↔ 复现状态 ↔ 冲突或缺口」逐项对齐。

> An evidence-grounded reconstruction Skill/Agent for bioinformatics papers. It keeps paper claims, figures, Methods, code behavior, runtime evidence, and biological interpretation in separate lanes, joins them only by stable IDs, and refuses to invent missing evidence.

---

## 典型用法（推荐）

本仓库的主要使用方式是**把它交给一个 AI 编码代理（coding agent）**，例如 ZCode、Claude Code、Codex 或其他能读 GitHub、读写文件、执行命令的 agent。你只需要提供三样东西：

1. **本仓库的链接**（即本页地址）；
2. **要读的文献**：论文链接（PubMed / journal / bioRxiv 等）或直接粘贴/上传全文（PDF、正文文本均可）；
3. **该文献相关的代码仓库链接**：论文对应的 GitHub/GitLab 仓库（分析代码、notebook、pipeline 等），有几个给几个。

然后把下面这段话发给你的 agent 即可：

```text
请严格按照 https://github.com/lcgaozzz/bioinfo-protocol-reconstructor 中
skills/dev-reconstruct-bioinfo-protocol/SKILL.md 定义的流程，
重建下面这篇文献的生物信息学分析：

- 文献：<论文链接 或 全文>
- 相关代码仓库：<GitHub 仓库链接，多个则逐行列出>
- （可选）补充材料 / 数据：<链接或文件>

要求：
- 逐项对齐论文主张、figure/panel、Methods 参数与代码实现；
- 生成 traceability.tsv、reconstruction_manifest.json、REPORT.md 和校验报告；
- 不补造任何论文未报告的参数；不能执行的步骤明确记为受阻，不要含糊带过。
```

Agent 会读取本仓库的 SKILL.md 与其引用的 references / schemas / scripts，在它自己的工作区里创建重建项目并产出证据包。

### 更多示例指令

- 「把这篇论文的 Figure 3、Methods 和代码逐项对齐，告诉我能否复现。」
- 「检查论文 Methods 与 notebook 参数是否冲突，并生成可追溯表。」
- 「代码暂时跑不了；请给出不补造参数的最小复现指导和阻塞项。」

## 支持的六种请求模式

同一个重建项目内可以混合以下模式：

| 模式 | 说明 |
| --- | --- |
| 完整重建 | 论文 → 图 → 方法 → 代码 → 结果的全链条证据包 |
| 图/面板解读 | 解释某个 figure/panel 是怎么做出来的、说明了什么 |
| 论文–代码–Methods 审计 | 找出参数冲突、死代码、缺失环节 |
| 执行/实证验证 | 在授权前提下实际运行并记录运行时证据 |
| 可执行代码指导 | 给出满足交付契约的最小复现命令（缺参数则明确阻塞） |
| 后续生物学解释 | 在证据允许范围内给出有边界的解读 |

## 你会得到什么

Agent 会在项目目录中产出：

| 产物 | 内容 |
| --- | --- |
| `traceability.tsv` | 八列追溯表：`analysis_id / 正文主张 / figure-panel / method与参数 / code位置 / 输入输出 / 复现状态 / 冲突或缺口` |
| `reconstruction_manifest.json` | 结构化证据、分析记录、执行记录、解释与衍生状态 |
| `source_inventory.json` | 来源清单：角色、定位符、可用性、指纹 |
| `working_state.json` | 六阶段进度、阻塞项与失效记录（可断点续跑） |
| `REPORT.md` | 从 manifest 渲染的人类可读报告，固定分节：直接证据 / 论文主张 / 重建支持 / 合理推断 / 无法验证 |
| `validation_report.json` | 校验器结果（含失败与警告） |

**只有四种合法复现状态**：`已执行验证` / `材料完整但未执行` / `受阻` / `材料冲突`。
`已执行验证` 必须有真实成功运行的证据（命令、环境与依赖版本、随机种子、指纹化的输入输出、机器重算的检查）；论文和代码冲突时即使代码能跑也记为 `材料冲突`。

## 核心原则

- **不编造**：论文未报告的参数一律保留为必填选项或显式缺口，绝不挑一个"合理值"冒充；
- **分道存放**：正文主张、图、Methods、代码、运行时证据、解释分属不同证据道（lane），只靠稳定 ID 关联；
- **运行时最高权威**：运行证据只证明"代码实际做了什么"，永远不改写"论文说了什么"；
- **不过度解释**：相关性不得升级为因果，富集分数不得冒充生化活性，时序排序不得当作发育时间；
- **fail-closed 校验**：校验器（`scripts/validate_reconstruction.py`）对结构、状态、证据绑定做严格机器校验，缺 `jsonschema` 4.x 时直接拒绝放行。

## 仓库结构

```text
bioinfo-protocol-reconstructor/
├── README.md                                  # 本文件
├── dev_reconstruct_bioinfo_protocol.md        # Agent（角色）定义：路由、权限、证据规则
└── skills/
    └── dev-reconstruct-bioinfo-protocol/      # Skill 本体
        ├── SKILL.md                           # 入口：目的、依赖顺序、证据与状态契约
        ├── TESTING.md                         # 开发验证说明
        ├── references/
        │   ├── workflow.md                    # 六阶段依赖门控工作流
        │   ├── evidence-contract.md           # 来源角色、证据类、追溯单元、状态推导
        │   ├── modality-audit.md              # 各组学模态的科学审计要点
        │   ├── code-and-execution.md          # 代码指导契约与执行契约
        │   └── reuse-routing.md               # 可选复用路由
        ├── schemas/
        │   └── reconstruction_manifest.schema.json
        ├── scripts/
        │   ├── validate_reconstruction.py     # 项目校验器
        │   ├── run_reconstruction.py          # 执行包装器（独立 run 目录）
        │   ├── finalize_execution.py          # 执行判定器（绑定检查与证据）
        │   └── execution_contract.py          # 内部共享工具（非独立入口）
        └── tests/                             # 合约测试（合成数据，非论文复现）
```

## 作为本地 Skill / Agent 安装（可选）

如果你使用 ZCode 或兼容的 agent 框架，可以安装为本地资源，而不必每次发仓库链接：

```bash
git clone https://github.com/lcgaozzz/bioinfo-protocol-reconstructor.git
# Skill：复制到你的 skills 目录
cp -r bioinfo-protocol-reconstructor/skills/dev-reconstruct-bioinfo-protocol <你的skills目录>/
# Agent 定义（可选）：复制 dev_reconstruct_bioinfo_protocol.md 到你的 agents 目录
```

## 本地校验与测试

对已产出的重建项目运行校验器（需 Python 3 + `jsonschema` 4.x）：

```bash
python skills/dev-reconstruct-bioinfo-protocol/scripts/validate_reconstruction.py \
  --project-dir <project_dir> --write-report
```

开发验证（合成合约测试，不涉及真实论文数据）：

```bash
python -B -m unittest discover \
  -s skills/dev-reconstruct-bioinfo-protocol/tests -p "test_*.py" -v
```

## 注意

- 校验器保证**结构与证据链完整性**，不能证明生物学正确性，也不能证明"流程→产物"的因果性；
- 本仓库的测试均为合成合约测试，不代表任何论文被成功复现过；
- Agent 在授权之外不会安装依赖、改动源数据或对外发布任何内容。
