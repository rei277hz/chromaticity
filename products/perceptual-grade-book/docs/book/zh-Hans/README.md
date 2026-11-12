# 简介

> **持续维护的手册：** 本出版物旨在跟进 Perceptual Grade 的最新版本。
> 用户手册描述的是 1.23.2 界面与工作流程；相关操作说明、宿主录像和
> 许多运行时工程内容仍落后于当前参考模型。下载与测量保留其原始版本
> 和范围。各章会注明所描述的产品或模型。

Perceptual Grade 将白平衡、自定义影调曲线与选择性色彩调整串成三个阶段。
Blender 实现提供用于着色与合成的节点；保留的 DCTL 运行于 DaVinci Resolve。
它们可用的控件与阶段 3 策略和最新参考模型有所不同，复现调色时请确认所用
实现的版本与范围。

<figure class="grade-demo"><img src="assets/intro/match-three-images.webp" data-still="assets/intro/match-three-images-still.webp" alt="匹配三张光照不同的图像" loading="eager"><figcaption>匹配三张光照不同的图像。随附录像是可替换的演示占位素材。</figcaption></figure>

<div class="download-grid">
<a class="download primary" href="downloads/perceptual_grade-v1.23.2-20261101.zip"><strong>获取开发版扩展</strong><span>Perceptual Grade 1.23.2 · 2026-11-01</span></a>
<a class="download" href="downloads/Perceptual-Grade.dctl"><strong>获取 DCTL</strong><span>DaVinci Resolve：英文</span></a>
<a class="download" href="downloads/Perceptual-Grade-zh-HANS.dctl"><strong>中文 DCTL</strong><span>DaVinci Resolve：简体中文</span></a>
</div>

下载的是日期为 2026-11-01 的 Perceptual Grade 1.23.2 开发构建，使用保留的
Perceptual Grade 实现，并非 Perceptual Grade Next，也会取代原有扩展下载。
下文的安装与日常流程仍描述 1.23.2 界面，尚未更新为 Next 或当前参考模型的
Warp 控件。

请从[安装](guide/install.md)开始，然后[分三个阶段调色](guide/workflow.md)。
在 **Linear** 中选择白点与色彩方向，在 **Tone** 中放置重要的场景色调，
再于 **Color** 中细化明度、彩度、适应与色相。[技术报告](https://rei277hz.github.io/perceptual-grade/technical/en/index.html)
介绍当前解析模型、相关计算以及实现背后的工程工作。

外观模型论文与实现参考见[致谢](reference/credits.md)，许可信息见[许可](reference/license.md)。
