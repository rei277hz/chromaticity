# 文档与媒体

本手册持续跟随最新 Perceptual Grade 参考模型。模型说明与当前数值图使用 `libraries/perceptual-grade-reference`；尚未更新的 1.23.2 使用指南、宿主录像和工程内容应注明版本。历史下载与测量保留原始含义。

`//products/perceptual-grade-book/generators:figures` 使用当前参考模型生成线性基、Tone、色调系数、驱动量和 H–K 修复图。Concentration 与历史 LUT 示例使用隔离的 1.23.2 模型；基准和 LUT 研究图沿用记录数据。每张图在 `figures.json` 中注明范围，来源清单记录参考与旧模型的哈希。Python 生成数值表，固定版本的 XeLaTeX/PGFPlots 输出静态 SVG，供网站、PDF 和 EPUB 共用。坐标轴保留英文，图注与替代文本分别翻译。

文档构建和检查命令见[手册产品 README](https://github.com/rei277hz/chromaticity/blob/main/products/perceptual-grade-book/README.md)。英文与简体中文应同步修订模型内容；历史测量不随文档构建重新测量。[下载图表源码与数据](../downloads/chart-sources.zip)可查看实际数值、图形定义与来源。
