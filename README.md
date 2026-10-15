# writing-forge

写作用的 agent skill：审查讲解文章能不能让读者建立正确的理解、把已有报告忠实地做成简报、为 GitHub 仓库设计 README 头图。每个 skill 是一个目录，核心是一份 `SKILL.md`，放进能读取 skill 目录的 agent 宿主即可使用。

> **English.** writing-forge is a small set of agent skills for writing work: auditing whether an explanatory article (a blog post, handout, or tutorial) builds the right mental model in its intended reader, turning an existing report into source-faithful slides, and designing a static SVG header for a GitHub README. Each skill is a folder with a `SKILL.md`; copy it into the skills directory your agent host reads. Most skills are written in Simplified Chinese; `piaget-article-auditor` is written in English and reports in the user's language.

> 状态：试用版（0.1.0）。每个 skill 都由一个只读公开稿的执行者在陌生样例上跑通过一次，并经独立审查；简报 skill 的样例只做到逐页内容表与 Mermaid，没有做到 PPT。样例都很小，没有更大规模的验证。

## 相关仓库

同一作者的其他 skill 仓库：

- [persona-masks-cn](https://github.com/asj252/persona-masks-cn)：让 AI 助手把「想、做、查」分开的一套轻量角色约定，做成文件型 skill。
- [chinese-math-forge](https://github.com/asj252/chinese-math-forge)：中文数学教材的写作与审查工具：数学严谨性审查、繁英翻译与习题流水线。
- [myst-textbook-forge](https://github.com/asj252/myst-textbook-forge)：用 MyST 写教科书的工具：章节编辑、视觉风格与 Python 代码整理。


## 包含的 skill

| skill | 做什么 | 正文语言 |
|---|---|---|
| [`piaget-article-auditor`](piaget-article-auditor/SKILL.md) | 用皮亚杰的同化／调适框架审查**单篇**讲解文章（科普、技术博客、教学讲义、单篇教程）：推断目标读者，找出隐性假设，逐个概念检查铺垫、例子与类比，检查代码与图的作用、标题承诺是否兑现，输出一份标明位置、严重度与改法的 Markdown 审查报告 | 英文；报告用提问的语言 |
| [`source-faithful-slides`](source-faithful-slides/SKILL.md) | 把已有的报告、讲稿或周报做成**忠于原文**的简报：核对模板缺口，逐页内容表与原文去向映射，每页 Mermaid 空间排版，样张确认后局部迭代；不替原文补结论 | 简体中文 |
| [`readme-header-design`](readme-header-design/SKILL.md) | 为 GitHub 仓库的 README 设计静态 SVG 头图：先读仓库、只写有依据的说法，按尺寸、字号与对比度的起点参数出图并渲染预览；不改 README 正文，不提交推送 | 简体中文 |

## 安装

把需要的 skill 目录整个复制到宿主读取 skill 的位置（各宿主一般有用户级与项目级两种 skills 目录，见宿主自己的文档），目录名保持与 `SKILL.md` 里的 `name` 一致：

```bash
git clone https://github.com/asj252/writing-forge.git
SKILLS_DIR="$HOME/path/to/skills"   # 先换成宿主实际读取的 skills 目录
mkdir -p "$SKILLS_DIR"
cp -r writing-forge/piaget-article-auditor "$SKILLS_DIR/"
```

整个目录一起复制：`readme-header-design/` 里的 `THIRD_PARTY_NOTICES.md` 是上游的 MIT 版权与许可声明，必须随该 skill 保留。

skill 只包含 Markdown 规则与参考文件，没有可执行脚本、服务或后台进程；安装只是复制文本文件。执行时用到的是宿主本身的能力：

- 三个 skill 都要能读写文件（读文章或仓库、写报告或产物）。
- `readme-header-design` 出预览需要一个能把 SVG 渲染成 PNG 的工具（skill 里给了几种可选的命令）。
- `source-faithful-slides` 做到 PPT 这一层需要宿主能读写与预览 PPTX；没有时只交付到逐页内容表与 Mermaid。

## 已知限制

- `source-faithful-slides`：Mermaid 的 `block-beta` 在信息密的页上排版不稳定：嵌套块里的跨列会把列宽成倍放大，一页同时放数据表、限定说明与多条发现时版面容易失衡。密集页建议先拆页，长标签用 `<br/>` 手动换行。
- `piaget-article-auditor`：严重度的判法已补强，并在定向回归里达标；在不提示判级的新样例上验证执行者能否自己判准，尚未完成。审查质量依赖宿主模型的阅读与判断，报告是给作者的修改建议，不是评分。
- `readme-header-design`：参数是从示例实测得来的起点，不同渲染器的字体回退会影响字宽，出图后要按预览调整。

## 许可与致谢

本仓库以 [Apache-2.0](LICENSE) 发布。

| 部分 | 来源 | 许可 |
|---|---|---|
| `piaget-article-auditor` | 作者新写；方法骨架取自作者自己的教材审查 skill | Apache-2.0 |
| `source-faithful-slides` | 作者自己的 skill，公开时去掉了个人偏好与项目内容，配色改为示例 | Apache-2.0 |
| `readme-header-design` | 改编自 [oil-oil/beautify-github-readme](https://github.com/oil-oil/beautify-github-readme) 的头图指南与 SVG 制作指南（翻译、删改与补充），部分参数来自对其示例 SVG 的实测 | 改编部分遵守上游 MIT 许可，声明见 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md)（skill 目录里也有一份）；作者的改动以 Apache-2.0 发布 |

变更记录见 [CHANGELOG.md](CHANGELOG.md)。
