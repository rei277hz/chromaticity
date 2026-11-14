# 致谢与参考文献

Perceptual Grade 由 Rei277Hz 开发。当前单体仓库源代码（包括 DCTL）采用
`MIT OR Apache-2.0` 许可；随附的 Blender 扩展及其对应源代码还以
`GPL-3.0-or-later` 许可提供。其解析式 DCTL 与原生扩展使用相同的调色模型。
当前许可政策及分别存档的历史下载详见[许可](license.md)。

## 色彩外观

Hellwig 与 Fairchild，2022 年发表的
[Brightness, lightness, colorfulness, and chroma in CIECAM02 and CAM16](https://doi.org/10.1002/col.22792)。

Hellwig 与 Fairchild，2022 年发表的
[Extending CIECAM02 and CAM16 for the Helmholtz–Kohlrausch effect](https://doi.org/10.1002/col.22793)。

Hellwig 与 Fairchild，2022 年发表的
[Revising CAM16-UCS](https://doi.org/10.2352/CIC.2022.30.1.48)。

[Colour 中的 Hellwig2022 实现](https://colour.readthedocs.io/en/develop/_modules/colour/appearance/hellwig2022.html)
是主要模型参考之一。

[Colour 中的 von Kries 适应实现](https://colour.readthedocs.io/en/develop/_modules/colour/adaptation/vonkries.html)
为 CAT16 适应提供参考。

原生 Stage 2 图与 NumPy 示波器实现共用 DCTL 的 modCAM16 坐标、H–K 补偿、色相
偏心率、默认校准及单调 softplus 重映射。该工具还加入了自身的带符号数值扩展、
影调系数模型、Adaptance 权重、色相集中度控件，以及有界 H–K 逆向保护。这些
工程选择在理论章节中说明。

## 稳健统计

Hubert、Rousseeuw 与 Verdonck 于 2012 年发表的
[A deterministic algorithm for robust location and scatter](https://wis.kuleuven.be/stat/robust/papers/2012/DetMCD.pdf)
提供了用于诊断轮廓的 DetMCD 算法。实现由本项目独立编写，使用六个确定性初值、
Qn 尺度、集中步骤和重加权；未包含 robustbase 或 scikit-learn 的代码。轮廓用于
描述诊断像素分布，不参与调色计算。

该论文发表于 *Journal of Computational and Graphical Statistics* 第 21 卷第 3 期，
第 618–637 页。原始 NumPy 实现现位于
`libraries/perceptual-grade-core/src/perceptual_grade_core/model/statistics.py`。
这是一个二维、有界样本实现，使用渐近高斯校正，并记录了退化情形与显示回退策略。

## 宿主与构建工具

Perceptual Grade 作为扩展运行于 [Blender](https://www.blender.org/) 内。该扩展使用
Blender 节点系统与色彩管理功能实现调色控件、示波器和渲染方式。

Perceptual Grade DCTL 在 DaVinci Resolve 中运行。
[Blackmagic Design 文档](https://www.blackmagicdesign.com/support/family/davinci-resolve-and-fusion)
介绍了宿主软件；DCTL 的界面说明请查阅对应版本随附的 DCTL 开发者文档。

[Buck2](https://buck2.build/) 用于构建生成资源、打包和运行测试。

[mdBook](https://rust-lang.github.io/mdBook/) 采用 MPL-2.0 许可，用于生成本静态手册。

[KaTeX](https://katex.org/) 采用 MIT 许可，通过 jsDelivr 上版本固定的 JavaScript、CSS
和字体渲染公式。脚本与样式表引用包含完整性哈希；这些资源文件本身不包含在部署
归档中。

构建会固定实际依赖版本及其哈希。第三方文档许可声明见
[mdBook](../downloads/licenses/mdbook-LICENSE) 和
[KaTeX](../downloads/licenses/katex-LICENSE) 许可文件。

## 教程与章节组织

ColorChecker2014 参考 EXR 由
[colour-science/colour-nuke](https://github.com/colour-science/colour-nuke)
提供，使用的固定提交记录在 `third_party/book/pins.bzl` 中。该文件依项目的
[BSD 许可](../downloads/licenses/colour-nuke-LICENSE)分发。

[ACES 输出变换结构文档](https://docs.acescentral.com/system-components/output-transforms/technical-details/rendering-overview/)
展示了如何围绕处理目的和方程说明各个阶段，并穿插数值图示。本手册中的计算与图示
生成器描述的是 Perceptual Grade 自身的模型。

## 主题与参考插图

阅读主题借鉴了 [ACES Documentation](https://docs.acescentral.com/) 的 Pontano Sans
字体、克制的配色、金色分隔线和导航布局。其中的
[extra.css](https://docs.acescentral.com/stylesheets/extra.css) 版权归 ACES 文档贡献者
所有，采用 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) 许可。此处的改编
调整了布局、对比度和 mdBook 集成；mdBook 页面布局与阅读控件也针对本手册进行了适配。
正文使用 Pontano Sans，代码使用 Roboto Mono；字体以版本固定的 WOFF2 文件形式从
jsDelivr 上的 Fontsource 发行包加载。其 SIL Open Font License 1.1 许可声明见
[Pontano Sans](../downloads/licenses/pontano-sans-OFL.txt) 和
[Roboto Mono](../downloads/licenses/roboto-mono-OFL.txt)。

外观模型简介重现了 Agahian 与 Stolitzka 发表的
[Modeling Perceived Brightness in HDR Displays](https://doi.org/10.2352/CIC.2025.33.1.7)
中的图 2 与图 3。该论文发表于第 33 届色彩与成像会议（2025 年），第 31–34 页。
这些图是未修改的参考插图，保留原作者署名，并作为可替换的源素材供审阅。其版权仍归
2025 年 Society for Imaging Science and Technology 出版物所有，不在项目原创艺术品
的授权范围内。它们说明已发表的模型，并非对本工具的测量结果。源信息与哈希记录于
`docs/data/appearance-references.json`。

[imageio-ffmpeg](https://github.com/imageio/imageio-ffmpeg) 提供固定版本的 FFmpeg
二进制文件，用于转换屏幕录像；Pillow 用于编码成对演示图及简介中的 WebP 演示。
