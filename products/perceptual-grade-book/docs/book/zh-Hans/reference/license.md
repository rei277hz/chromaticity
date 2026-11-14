# 许可证

版权所有 © 2026 Rei277Hz。

## 仓库源代码

上游开发仓库 [rei277hz/chromaticity](https://github.com/rei277hz/chromaticity) 的原创源代码采用双许可证，使用者可自行选择
[MIT 许可证](https://github.com/rei277hz/chromaticity/blob/main/LICENSE-MIT)
或 [Apache 许可证 2.0 版](https://github.com/rei277hz/chromaticity/blob/main/LICENSE-APACHE)
（`MIT OR Apache-2.0`）。这包括 Blender 产品源代码、共享库、Web 产品、构建工具及
DCTL。DCTL 遵循仓库根目录的许可证，不另设产品许可证。

[rei277hz/perceptual-grade](https://github.com/rei277hz/perceptual-grade) 是用于代码分发的下游快照仓库，当前存放的是
2026-11-01 构建的旧版 Perceptual Grade v1.23.2 代码，并非 Perceptual Grade Next。
接受 Issues，不接受 PR；所有 PR 请提交到 `rei277hz/chromaticity`。
具体链接见[参与贡献](../development/contributing.md)。

## Blender 扩展发行包

Blender 扩展发行包中的原创代码及其对应源代码（Corresponding Source）另以
GNU 通用公共许可证第 3 版或任何后续版本（`GPL-3.0-or-later`）提供。
这一额外授权不会撤销仓库源代码已有的 MIT 或 Apache-2.0 授权。

各 Blender 产品目录中的 `LICENSE` 是打包输入：它包含发行授权说明和完整的
GPLv3 正文，并作为 ZIP 中唯一的 `LICENSE` 文件。它不替代仓库根目录的源代码许可证。
ZIP 不另外包含 MIT/Apache 许可证文本或 `NOTICE.md`，清单声明为
`license = ["SPDX:GPL-3.0-or-later"]`。

对应源代码指修改该发行版本时首选的形式，包括生成代码所需的生成器输入及构建脚本。
发行下载必须标明并提供与发行版本准确对应的这些源代码，并适用上述额外 GPL 授权。
通用构建工具及无关的 monorepo 产品不会因此获得 GPL 授权。
详见 [GPLv3 第 1 节及第 6 节](https://www.gnu.org/licenses/gpl-3.0.html)。

发行时应从已提交的发行版本用 `git archive` 创建完整 monorepo 源代码归档，
从该归档的干净解压目录构建扩展 ZIP，并将源代码归档与扩展 ZIP 一起发布。
发行页面必须标明确切的提交编号并提供对应源代码归档的链接。这样可以保留生成器输入及
构建脚本，而无需把它们加入安装 ZIP。指向持续变化的分支的链接不能准确标识发行源代码。

## 素材、第三方材料与历史下载

上述 GPL 授权针对代码。Blender 扩展发行包中包含的原创非代码素材采用
[CC0 1.0](https://creativecommons.org/publicdomain/zero/1.0/)，具体范围在包内
`LICENSE` 中标明，以符合
[Blender Extensions 的许可证要求](https://extensions.blender.org/terms-of-service/)。
此授权不会改变第三方数据、参考插图、字体及其他署名材料的许可；这些材料仍保留原有条款与署名。
详见[致谢与参考文献](credits.md)。

本手册在持续更新的同时保留历史版本下载。提供的
[日期为 2026-11-01 的 Perceptual Grade 1.23.2 开发版 ZIP](../downloads/perceptual_grade-v1.23.2-20261101.zip)
已替换原扩展下载，该下载适用 ZIP 内的许可证。归档的 DCTL 下载、原始运行时声明及
[历史 GPL 许可证](../downloads/licenses/perceptual-grade-LICENSE)
均保持原样，沿用历史发行条款。本页说明当前 monorepo 与扩展发行包的许可政策，
不会改写这些归档文件。
