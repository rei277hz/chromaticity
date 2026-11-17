# Blender 感知调色

Perceptual Grade 是用于 Blender 着色器和合成器节点编辑器的三阶段色彩变换。
当前 Next 实现提供 **Linear**、**Tone** 与 **Color** 控件、共享调色、节点自有
动画调色、调色栈和受管理的图像烘焙。[技术报告](https://rei277hz.github.io/perceptual-grade/technical/en/index.html)
介绍模型及当前实现约定。

<div class="download-grid">
<a class="download primary" href="downloads/perceptual_grade-v1.23.2-20261101.zip"><strong>旧版 Blender 下载</strong><span>Perceptual Grade 1.23.2 · 2026-11-01 · 并非 Next</span></a>
</div>

上方 ZIP 仅为保留的 1.23.2 扩展，供旧版用户使用，其中不包含 Perceptual Grade
Next。本手册目前尚未提供 Next 扩展 ZIP。

请从[安装与节点连接](guide/install.md)开始，再按[三个阶段调色](guide/workflow.md)
操作。在 **Linear** 中处理场景工作空间下的白平衡和颜色关系，在 **Tone** 中
设置影调锚点，在 **Color** 中调整明度、彩度、Adaptance 和六点 Warp 色网。共享
调色可供多个节点复用；若节点需要独立动画，可转换为节点自有设置。调色栈则把
按顺序排列的正向条目合并为一次采样变换。

本手册介绍 Blender 着色器和合成器节点。[参考章节](https://rei277hz.github.io/perceptual-grade/technical/en/index.html)
讲解数学模型；[Next 策略章节](https://rei277hz.github.io/perceptual-grade/technical/en/development/next-policies.html)记录运行时发布、
故障处理和烘焙行为。

模型和实现参考见[致谢](reference/credits.md)，许可信息见[许可证](reference/license.md)。
