# 简介

> **持续维护的手册：** 本书旨在跟随 Perceptual Grade 的最新版本。[理解模型](theory/structure.md) 遵循 `libraries/perceptual-grade-reference` 中的当前解析参考模型。部分内容仍然滞后：使用指南、宿主录像和许多运行时工程说明还停留在 1.23.2。下载与测量保留其原始版本含义。英文版另有介绍 Next 当前策略的章节；Next 尚未实现 Warp。模型、实现与历史章节会分别注明范围。

[rei277hz/perceptual-grade](https://github.com/rei277hz/perceptual-grade) 是用于代码分发的下游快照仓库，当前存放的是
2026-11-01 构建的旧版 Perceptual Grade v1.23.2 代码，并非 Perceptual Grade Next。
接受 Issues，不接受 PR。所有 PR 请提交到上游
[rei277hz/chromaticity](https://github.com/rei277hz/chromaticity)；具体链接见
[参与贡献](development/contributing.md)。

Perceptual Grade 把白平衡、自定义影调曲线与选择性色彩调整串成三个阶段。Blender 实现提供用于着色与合成的节点；保留的 DCTL 运行于 DaVinci Resolve。它们的可用控件与阶段 3 策略和最新参考模型有所不同，复现调色时需要区分实现版本。

<figure class="grade-demo"><img src="assets/intro/match-three-images.webp" data-still="assets/intro/match-three-images-still.webp" alt="匹配三张光照不同的图像" loading="eager"><figcaption>匹配三张光照不同的图像。随附的录像是可替换的演示占位素材。</figcaption></figure>

<div class="download-grid">
<a class="download primary" href="downloads/perceptual_grade-v1.23.2-20261101.zip"><strong>获取开发版扩展</strong><span>Perceptual Grade 1.23.2 · 2026-11-01</span></a>
<a class="download" href="downloads/Perceptual-Grade.dctl"><strong>获取 DCTL</strong><span>DaVinci Resolve：英文</span></a>
<a class="download" href="downloads/Perceptual-Grade-zh-HANS.dctl"><strong>中文 DCTL</strong><span>DaVinci Resolve：简体中文</span></a>
</div>

下载的是日期为 2026-11-01 的 Perceptual Grade 1.23.2 开发构建，使用保留的 Perceptual Grade 实现，并非 Perceptual Grade Next。下面的安装与日常流程仍描述 1.23.2 界面，尚未更新为 Next 或当前参考模型的 Warp 控件。

请从[安装](guide/install.md)开始，然后[分三个阶段调色](guide/workflow.md)。在 **Linear** 中选择白点与色彩方向，在 **Tone** 中放置重要的场景色调，在 **Color** 中细化明度、彩度、适应与色相。

手册先讲解日常使用。[理解模型](theory/structure.md) 随后说明计算过程及其数值图示。开发者可从[架构](development/architecture.md)、[构建与测试](development/building.md)或[参与贡献](development/contributing.md)开始。

1.23.2 指南中的控件包括 Hue Concentration、Adaptance Strength 与 Fit，以及全局低彩度和高彩度 Hue 系数。当前参考模型使用跨越四个色调行的六个色相手柄、由中性色落点驱动的选择性锥体适应、H–K 修复，以及随后对无彩明度和彩度的共同正缩放。两者的保存设置不会被相互重新解释。[色彩一章](theory/color.md)说明当前阶段，并单独标注保留的旧控件。

随附下载由 Buck2 与本手册一起打包。外观模型论文与实现参考见[致谢](reference/credits.md)，许可信息见[许可](reference/license.md)。
