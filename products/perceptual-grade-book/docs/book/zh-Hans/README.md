# 简介

> **版本范围：** 使用指南、下载与已记录的测量描述 Perceptual Grade 1.23.2。[理解模型](theory/structure.md) 则遵循 `libraries/perceptual-grade-reference` 中的解析参考模型，该模型已超出 1.23.2。每一章都会说明自己描述的是哪一个。

[rei277hz/perceptual-grade](https://github.com/rei277hz/perceptual-grade) 是用于代码分发的下游快照仓库，当前存放的是
2026-11-01 构建的旧版 Perceptual Grade v1.23.2 代码，并非 Perceptual Grade Next。
接受 Issues，不接受 PR。所有 PR 请提交到上游
[rei277hz/chromaticity](https://github.com/rei277hz/chromaticity)；具体链接见
[参与贡献](development/contributing.md)。

Perceptual Grade 把白平衡、自定义影调曲线与选择性色彩调整串成三个阶段。其 Blender 扩展提供用于着色与合成的 Perceptual Grade 节点；其解析 DCTL 运行于 DaVinci Resolve。两种实现共享同一套调色模型与控件。

<figure class="grade-demo"><img src="assets/intro/match-three-images.webp" data-still="assets/intro/match-three-images-still.webp" alt="匹配三张光照不同的图像" loading="eager"><figcaption>匹配三张光照不同的图像。随附的录像是可替换的演示占位素材。</figcaption></figure>

<div class="download-grid">
<a class="download primary" href="downloads/perceptual_grade-v1.23.2-20261101.zip"><strong>获取开发版扩展</strong><span>Perceptual Grade 1.23.2 · 2026-11-01</span></a>
<a class="download" href="downloads/Perceptual-Grade.dctl"><strong>获取 DCTL</strong><span>DaVinci Resolve：英文</span></a>
<a class="download" href="downloads/Perceptual-Grade-zh-HANS.dctl"><strong>中文 DCTL</strong><span>DaVinci Resolve：简体中文</span></a>
</div>

下载的是日期为 2026-11-01 的 Perceptual Grade 1.23.2 开发构建，使用保留的 Perceptual Grade 实现，并非 Perceptual Grade Next，并已替换原扩展下载。下面的安装与日常流程描述的是该构建，尚未针对这一开发构建更新。

请从[安装](guide/install.md)开始，然后[分三个阶段调色](guide/workflow.md)。在 **Linear** 中选择白点与色彩方向，在 **Tone** 中放置重要的场景色调，在 **Color** 中细化明度、彩度、适应与色相。

手册先讲解日常使用。[理解模型](theory/structure.md) 随后说明计算过程及其数值图示。开发者可从[架构](development/architecture.md)、[构建与测试](development/building.md)或[参与贡献](development/contributing.md)开始。

模型部分与使用指南描述的是不同阶段，这一差异并非表面文章。1.23.2 的控件包括 Hue Concentration、Adaptance Strength 与 Fit，以及全局低彩度与高彩度 Hue 系数。解析参考用一张跨越四个色调行的六手柄色调网、由直接中性色落点驱动的选择性锥体适应，以及最终彩度缩放取代了它们。两者的保存设置不会被相互重新解释。[色彩一章](theory/color.md)描述参考阶段，并把 1.23.2 的控件保留在单独标注的小节中，因此可以分辨每句话属于哪一个。

随附下载由 Buck2 与本手册一起打包。外观模型论文与实现参考见[致谢](reference/credits.md)，许可信息见[许可](reference/license.md)。
