# 线性

> **保留版本：** 本使用章节及截图描述 1.23.2，仍滞后于最新模型。当前参考见[理解模型](../theory/structure.md)；这些控件并非 Next 未来的 Warp 实现。

线性校正为图像的创意调色建立可靠起点。它修正整幅图像的光照偏色与整体色彩关系，让 Tone 和 Color 可以塑造观感，而不必补偿不需要的色偏。Global Exposure 提高或降低整体亮度；先建立合适的亮度，再依次处理白平衡与下面的色彩关系。

## 平衡白点与色彩关系

Source White 就是常见的白平衡调整：让应该呈现为白色的区域真正显示为白色。寻找在预期光照下应当中性的表面，例如白纸、灰卡或色卡的中性色块。结合表面本身与示波器轨迹判断；有色物体不是白点参考。

在每个示例中，先拖动扩展的 Linear 矢量示波器，直到中性表面不再有不需要的偏色。将 Source White 重置到起始位置，再直接拖动源白点，重复完成校正。这是同一种调整的两种操作方式。保留第二次校正的结果，继续下一段演示。

在 Resolve 中，将 Perceptual Grade DCTL 的 Source White 设为 Custom xy，再调整 Source White x 和 Source White y。这两个滑块可以重现任一种拖动操作。Destination White 保持为 CST 设置所确定的值。

<figure class="grade-demo">
<img src="../assets/demos/linear-white-balance.webp" data-still="../assets/demos/linear-white-balance-still.webp" alt="A 和 B 先拖动矢量示波器校正白平衡，重置 Source White，再通过拖动源白点重复校正。" loading="lazy">
<figcaption>两张图像都先拖动矢量示波器，重置 Source White，再直接拖动源白点。保留最终的白平衡。</figcaption>
</figure>

Balance 在保持已确定白点不变的同时，改变相对颜色的亮度关系。增加 Cyan-Red Balance 会让青色相对红色更亮；增加 Yellow-Blue Balance 会让黄色相对蓝色更亮。当中性表面已经正确，而某一组颜色的一侧显得过亮或过重时，这类调整很有用。

Spread 和 Heading 以另一种方式改变这些关系。更宽的 Spread 通常让该方向的颜色更饱和；更窄的 Spread 则让它们趋近白色。Heading 旋转方向，从而改变色相。全部六个控件都会保持已确定的白点，所以这些调整不会撤销白平衡。

接着第一段演示，使用两个 Balance 手柄、两个 Spread 手柄和两个 Heading 手柄。在 A 中，平衡相对颜色的亮度，扩展偏灰的色彩关系并细调色相；在 B 中，平衡另一组亮度关系，收敛较强的色彩并细调色相。每次改变一种关系时，都要观察完整图像。

DCTL 中对应的六个滑块为 Cyan-Red Balance、Yellow-Blue Balance、Cyan-Red Spread、Yellow-Blue Spread、Cyan-Red Heading 和 Yellow-Blue Heading。

<figure class="grade-demo">
<img src="../assets/demos/linear-correction.webp" data-still="../assets/demos/linear-correction-still.webp" alt="A 和 B 保留白平衡，分别使用两个 Balance 手柄以及四个 Spread 和 Heading 手柄来实现不同目的。" loading="lazy">
<figcaption>其余六个控件：两个 Balance 手柄、两个 Spread 手柄和两个 Heading 手柄；保留前面完成的白平衡。</figcaption>
</figure>

## 示例：匹配拍摄到的 ColorChecker

接着 Linear 调整继续操作。使用在待校正光照下拍摄的 ColorChecker，并以 [ColorChecker2014 EXR](../downloads/ACEScg_ColorChecker2014.exr) 为参考。参考图像采用 ACEScg，请在其 Image Texture 或 Image 节点上显式设置该色彩空间；同时正确设置照片自身的输入编码。

将照片连接到 Color，将 EXR 的 Color/Image 输出连接到 Color Reference。裁切并旋转拍摄的色卡，使其与 EXR 的构图一致，并尽可能减少背景。调色作用于 Color；Color Reference 提供独立的对照轨迹。

![ColorChecker EXR 连接到 Color Reference](../assets/screenshots/colorchecker-connect.png)

<p class="figure-caption">照片与 ACEScg EXR 图像节点、两条连接，以及显示参考轨迹的 Linear 矢量示波器。</p>

先比较中性色块。细调 Source White 和 Global Exposure，再使用 Balance、Spread 和 Heading 手柄，让彩色色块的读数靠近参考值。同时观察多个色块：单一全局矩阵是一种折中，光照、眩光和相机渲染都可能使精确匹配无法实现。将得到的校正结果带入 Tone。

<figure class="grade-demo">
<img src="../assets/demos/colorchecker-match.webp" data-still="../assets/demos/colorchecker-match-still.webp" alt="通过对齐中性色块与彩色色块的矢量示波器读数，将每张色卡照片与 EXR 参考匹配。" loading="lazy">
<figcaption>通过对齐中性色块与彩色色块的矢量示波器读数，将每张色卡照片与 EXR 参考匹配。</figcaption>
</figure>

在 Linear 中，红色参考轨迹绘制在主轨迹上方。单击示波器或 Tone 曲线的空白区域，会切换所有阶段的参考显示；拖动 Linear 矢量示波器则调整源白点。单击与拖动各有不同用途。

在 Tone 中，参考显示于 After 波形和曲线直方图。在 Color 中，波形与矢量示波器会显示所选输入色调区域的对应位置。各直方图高度分别归一化，因此它们的高度并不能用于测量曝光。

扩展的波形测量感知明度，而矢量示波器显示显示端 Rec.709 信号彩度。Resolve 的原生示波器使用其所选宿主刻度。在 Resolve 中，应让照片与参考经过相同的 CST 和显示处理链进行比较，再使用上述同名 Linear 滑块；DCTL 没有扩展中的 Color Reference 插口。

示波器采样支持平面图像、Render Layers 的色彩通道、RGB 常量、转接节点和 Perceptual Grade 链。使用 Render Layers 时请先渲染；程序化节点网络无法采样时，请使用烘焙图像。
