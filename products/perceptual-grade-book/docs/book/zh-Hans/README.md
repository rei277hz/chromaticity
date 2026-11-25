# Blender 感知调色

Perceptual Grade 是用于 Blender 着色器和合成器节点编辑器的三阶段色彩变换。
Perceptual Grade 提供 **Linear**、**Tone** 与 **Color** 控件、共享调色、节点自有
动画调色、调色栈和受管理的图像烘焙。[技术报告](https://rei277hz.github.io/perceptual-grade/technical/en/index.html)
介绍模型与产品实现。

<div class="download-grid">
<a class="download primary" href="downloads/archived-blender-extension.zip"><strong>归档的 Blender 扩展</strong><span>预构建归档</span></a>
</div>

此归档 ZIP 是本书唯一提供的扩展下载，其界面与本手册介绍的当前工作流有所不同。

请从[安装与节点连接](guide/install.md)开始，再按[三个阶段调色](guide/workflow.md)
操作。在 **Linear** 中处理场景工作空间下的白平衡和颜色关系，在 **Tone** 中
设置影调锚点，在 **Color** 中调整明度、彩度、Adaptance 和六点 Warp 色网。共享
调色可供多个节点复用；若节点需要独立动画，可转换为节点自有设置。调色栈则把
按顺序排列的正向条目合并为一次采样变换。

本手册介绍 Blender 着色器和合成器节点。[参考章节](https://rei277hz.github.io/perceptual-grade/technical/en/index.html)
讲解数学模型；[运行时策略章节](https://rei277hz.github.io/perceptual-grade/technical/en/development/policies.html)记录运行时发布、
故障处理和烘焙行为。

模型和实现参考见[致谢](reference/credits.md)，许可信息见[许可证](reference/license.md)。
