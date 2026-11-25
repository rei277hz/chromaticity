# 致谢与参考文献

Perceptual Grade 由 Rei277Hz 及其贡献者开发。当前解析式参考实现和产品适配器维护于
[chromaticity 仓库](https://github.com/rei277hz/chromaticity)。源代码与产品包的许可条款见
[许可证](license.md)。

## 色彩外观

Hellwig 与 Fairchild 于 2022 年发表的论文：[Brightness, lightness, colorfulness, and chroma in
CIECAM02 and CAM16](https://doi.org/10.1002/col.22792)。

Hellwig 与 Fairchild 于 2022 年发表的论文：[Extending CIECAM02 and CAM16 for the Helmholtz–Kohlrausch
effect](https://doi.org/10.1002/col.22793)。

Hellwig 与 Fairchild 于 2022 年发表的论文：[Revising CAM16-UCS](https://doi.org/10.2352/CIC.2022.30.1.48)。

[Colour 的 Hellwig2022 实现](https://colour.readthedocs.io/en/develop/_modules/colour/appearance/hellwig2022.html)
是外观模型的重要实现参考。
[Colour 的 von Kries 适应实现](https://colour.readthedocs.io/en/develop/_modules/colour/adaptation/vonkries.html)
为 CAT16 色适应提供参考。

## 产品宿主与工具

Blender 扩展使用 Blender 的节点、合成器和色彩管理系统。Resolve DCTL 产品使用
DaVinci Resolve 的 DCTL 接口和 GPU 执行功能。有关宿主特定行为，请参阅已安装宿主随附的文档。

[Buck2](https://buck2.build/) 用于构建产品、生成资源、运行测试及构建文档。
[mdBook](https://rust-lang.github.io/mdBook/) 用于生成静态书籍。
[KaTeX](https://katex.org/) 用于在网站和印刷输出中渲染公式。

本书使用来自 [colour-science/colour-nuke](https://github.com/colour-science/colour-nuke)
的 ColorChecker2014 参考 EXR。其固定提交记录在 `third_party/book/pins.bzl` 中，文件依据
BSD 许可证提供。出版物在需要时附上第三方许可证与声明。

## 主题与插图

阅读主题的字体、导航和布局改编自
[ACES Documentation](https://docs.acescentral.com/)，并遵循
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 许可。改编内容调整了布局、对比度和 mdBook 集成。

外观模型简介重现了 Agahian 与 Stolitzka 的论文
[Modeling Perceived Brightness in HDR Displays](https://doi.org/10.2352/CIC.2025.33.1.7)
中的图 2 和图 3。该论文发表于 2025 年第 33 届色彩与成像会议，第 31–34 页。图示保留原作者署名与出版版权，
仅用于说明已发表的模型，并非 Perceptual Grade 的测量结果。源信息与哈希记录于
`docs/data/appearance-references.json`。
