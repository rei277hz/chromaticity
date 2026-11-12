# 安装与连接

> **保留版本：** 本使用章节及截图描述 1.23.2，仍滞后于最新模型。当前参考见[理解模型](../theory/structure.md)；这些控件并非 Next 未来的 Warp 实现。

## Blender 扩展

下载[开发版扩展 perceptual_grade-v1.23.2-20261101.zip](../downloads/perceptual_grade-v1.23.2-20261101.zip)。
这是日期为 2026-11-01 的 Perceptual Grade 1.23.2 开发构建，使用保留的 Perceptual Grade 实现，并非 Perceptual Grade Next。
此 ZIP 已替换原扩展下载。本章描述旧版 1.23.2 工作流程，尚未针对该开发构建更新。

在 Blender 的偏好设置中打开插件页面，通过菜单选择“从磁盘安装”（Install from Disk），选中 ZIP 并启用 Perceptual Grade。在着色器或合成器编辑器中，选择“添加 → 颜色 → Perceptual Grade”。选中节点后打开其 Perceptual Grade 侧栏。

![安装 Blender 扩展](../assets/screenshots/blender-install.png)

<p class="figure-caption">“从磁盘安装”以及已启用的 Perceptual Grade 扩展。</p>

### 在着色器中连接材质

将 Image Texture 的 Color 输出连接到 Perceptual Grade 的 Color 输入，再把调色后的 Color 连接到需要调整的材质输入，例如 Principled BSDF 的 Base Color；着色器仍需连接到 Material Output。若要预览不受照明影响的图像，可把调色后的颜色连接到 Emission 着色器。

![着色器节点连接](../assets/screenshots/blender-shading.png)

<p class="figure-caption">Image Texture → Perceptual Grade → 着色器 → Material Output。图示同时显示节点接口与图像。</p>

### 在合成器中连接图像

在合成器中启用 Use Nodes。将 Image 或 Render Layers 的 Image 输出连接到 Perceptual Grade 的 Color 输入，再将调色后的 Color 送到下一步合成操作或输出。添加 Viewer 分支，以便拖动控件时观察结果。在采样 Render Layers 之前先渲染一次。

![合成器节点连接](../assets/screenshots/blender-compositing.png)

<p class="figure-caption">Image 或 Render Layers → Perceptual Grade → 输出，另接 Viewer 分支。</p>

把每张源图像的 Color Space 设置为其真实编码，使 Blender 正确解码。暂时不要连接 Color Reference；[ColorChecker 示例](linear.md#示例匹配拍摄到的-colorchecker)会介绍它的用法。

## DaVinci Resolve DCTL

下载[英文 DCTL](../downloads/Perceptual-Grade.dctl)或[简体中文 DCTL](../downloads/Perceptual-Grade-zh-HANS.dctl)。在 Project Settings → Color Management → Lookup Tables 中选择 Open LUT Folder，把文件复制到该目录，然后选择 Update Lists。在 Color 页面为串行节点添加 DCTL Resolve FX 效果，选中 Perceptual-Grade。

![安装 Resolve DCTL](../assets/screenshots/resolve-install.png)

<p class="figure-caption">安装后的文件、Update Lists，以及 DCTL 效果的文件选择框。</p>

### 在 DCTL 两侧显式放置 CST

使用不启用自动色彩管理的 DaVinci YRGB 项目，并添加三个串行节点。

第一个节点放置输入 Color Space Transform。Input Color Space 与 Input Gamma 应匹配素材，Output Color Space 设为 CIE XYZ，Output Gamma 设为 Linear。

第二个节点放置 Perceptual Grade。它接收并输出线性 XYZ；Destination White 应设为该信号所表示的白点。

第三个节点放置输出 Color Space Transform。Input Color Space 设为 CIE XYZ、Input Gamma 设为 Linear，再选择用于监看或交付的输出空间与伽马。

对于 D65 链路，例如转换为 XYZ 的 Rec.709 SDR 或 Rec.2020 PQ 素材，使用 Destination White = D65，并在输出 CST 中保持一致。ACES 白点的 XYZ 链路使用 ACES；明确采用日光 D60 的链路选择 D60 daylight，其坐标与 ACES 白点不同。XYZ 本身不指定白点，应匹配实际转换，而不是依据相机名称或画面的偏色。Source White 才是用于消除偏色的调色控件。

图示 D65 链路的两个 CST 都关闭 Use White Point Adaptation，以保留该白点。如果有意适应到另一白点，则应把 Destination White 设为适应后信号的白点。XYZ 中的 D65 中性色满足 \(X/Y\approx0.9505\)、\(Z/Y\approx1.089\)；开始调色前可用中性色块检查转换。

![Resolve CST 与白点设置](../assets/screenshots/resolve-cst.png)

<p class="figure-caption">输入 CST、DCTL 的 Destination White 和输出 CST，以及完整的三节点链路。</p>

设置调色链路时，关闭转换 CST 的自动影调映射、色域映射、Apply Forward OOTF 和 Apply Inverse OOTF。HDR 转 SDR 监看应在下游有意设置显示变换。检查线性信号的尺度：DCTL 把 \(Y=1\) 视为 Reference Nits。如果转换按另一亮度归一化，应在 DCTL 前显式缩放，并在其后做相反调整。

演示使用 Blender 中 Perceptual Grade 扩展的操控器。Resolve 用户可用各段演示旁列出的 DCTL 滑块名称重现操作。

Grade 选择框初始为空。首次调色编辑会创建可复用的 Grade；节点共享和独立副本的用法见[共享与复用调色](shared-grades.md)。
