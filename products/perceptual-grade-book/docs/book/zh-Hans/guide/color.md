# 色彩

> **保留版本：** 本使用章节及截图描述 1.23.2，仍滞后于最新模型。当前参考见[理解模型](../theory/structure.md)；这些控件并非 Next 未来的 Warp 实现。

保留 Linear 和 Tone 的调整结果。以下操作在两个示例中都接着前一步继续进行，不要在录像之间重置。A 始终为 SDR，B 始终为 HDR。在 Resolve 中，请使用每段演示旁列出的 Perceptual Grade DCTL 滑块。

点击曲线上的圆点、S/M/W/H 标签或波形指示线来选择色调区域。曲线高度表示调整强度，并不是最终像素值。Cₗ 侧重低彩度颜色，Cₕ 侧重高彩度颜色，两者都采用平滑权重。示波器显示所选输入色调区域经过调色后的结果。

## 明度 J 曲线：每张图像调整两个色调区域

选择 Lightness J 和 Cₗ 曲线。在 A 中提亮 Shadows，并让 White 稍微更突出；在 B 中提亮 Midtones，同时收敛 Highlights。两张图像都用同一种手柄调整两个色调区域，以实现不同目的。

<figure class="grade-demo">
<img src="../assets/demos/color-j.webp" data-still="../assets/demos/color-j-still.webp" alt="明度 J：A 调整 Shadows 和 White；B 调整 Midtones 和 Highlights。" loading="lazy">
<figcaption>明度 J：A 调整 Shadows 和 White；B 调整 Midtones 和 Highlights。</figcaption>
</figure>

DCTL 滑块：A 使用 Shadows Cₗ → J 和 White Cₗ → J；B 使用 Midtones Cₗ → J 和 Highlights Cₗ → J。处理高彩度颜色时，改用对应的 Cₕ → J 滑块。Lightness Fit 控制各色调系数融合的范围。

## 明度 J 与彩度 C 曲线：共用一个色调区域

在两个示例中都选择 Midtones。先调整 Cₗ → J 曲线，再切换到 Chroma C，保持色调选择不变并调整 Cₗ → C。A 可以提亮偏灰的主体并增加色彩；B 可以压低过于突出的中间调并减弱其色彩。这两类接收通道共同作用于同一个色调区域。

<figure class="grade-demo">
<img src="../assets/demos/color-jc-curves.webp" data-still="../assets/demos/color-jc-curves-still.webp" alt="两个示例都选择 Midtones，并组合使用 Lightness J 和 Chroma C 曲线。" loading="lazy">
<figcaption>两个示例都选择 Midtones，并组合使用 Lightness J 和 Chroma C 曲线。</figcaption>
</figure>

DCTL 滑块：Midtones Cₗ → J 和 Midtones Cₗ → C。对应的高彩度控件为 Midtones Cₕ → J 和 Midtones Cₕ → C。彩度贡献获得完整权重时，+1 使 C 加倍，−1 使其减半。Chroma Fit 塑造调整在色调上的影响范围；Global C Gain 则改变所有色调区域的彩度。

## 明度 J 与彩度 C 的 a/b 平面：共用一个色调区域

在两张图像中都保持 Midtones 选中。在 Lightness J 平面中移动手柄，提高一个色相方向的明度，同时降低其相反方向。切换到 Chroma C，沿同一方向调整色彩强度。A 可以让主体从背景中更突出；B 可以削弱干扰色，同时保留主体。这是在每张图像的同一色调区域上配合使用 J 和 C 调整。

<figure class="grade-demo">
<img src="../assets/demos/color-jc-pads.webp" data-still="../assets/demos/color-jc-pads-still.webp" alt="两个示例都使用 Midtones 的 a/b 平面，组合调整特定方向的明度和彩度。" loading="lazy">
<figcaption>两个示例都使用 Midtones 的 a/b 平面，组合调整特定方向的明度和彩度。</figcaption>
</figure>

DCTL 滑块：Midtones a → J、Midtones b → J、Midtones a → C 和 Midtones b → C。沿对角线移动会组合 a 与 b 的作用。扩展的平面中，+a 向上，+b 向左，与其矢量示波器的方向一致。

## Adaptance 平面：每张图像调整两个色调区域

选择 Adaptance。在 A 中减轻 Shadows 的偏色，再细调 White；在 B 中校正 Midtones，再细调 Highlights。移动各色调区域的手柄时，观察该区域内应接近中性的表面。

<figure class="grade-demo">
<img src="../assets/demos/color-adaptance.webp" data-still="../assets/demos/color-adaptance-still.webp" alt="Adaptance：A 调整 Shadows 和 White；B 调整 Midtones 和 Highlights。" loading="lazy">
<figcaption>Adaptance：A 调整 Shadows 和 White；B 调整 Midtones 和 Highlights。</figcaption>
</figure>

在 DCTL 中，A 使用 Shadows Adaptance a、Shadows Adaptance b、White Adaptance a 和 White Adaptance b。B 使用 Midtones Adaptance a、Midtones Adaptance b、Highlights Adaptance a 和 Highlights Adaptance b。

Adaptance Strength 控制调整量和彩度保护；Adaptance Fit 控制色调间的融合。平面上的均值十字与置信范围描述采样到的近中性像素，并放大 5×，便于看清细微偏色。

## 色相集中平面：每张图像调整两个色调区域

选择 Hue，并使用其 a/b concentration 平面。在 A 中，先收拢 Shadows 中分散且干扰画面的色相，再细调 White；在 B 中，先收拢 Midtones 的色相，再细调 Highlights。Concentration 会将色相拉向所选方向，并扩大相反一侧色相间的距离。

<figure class="grade-demo">
<img src="../assets/demos/color-hue-pad.webp" data-still="../assets/demos/color-hue-pad-still.webp" alt="色相集中：A 调整 Shadows 和 White；B 调整 Midtones 和 Highlights。" loading="lazy">
<figcaption>色相集中：A 调整 Shadows 和 White；B 调整 Midtones 和 Highlights。</figcaption>
</figure>

DCTL 滑块：A 使用 Shadows Hue Concentration a、Shadows Hue Concentration b、White Hue Concentration a 和 White Hue Concentration b。B 使用 Midtones Hue Concentration a、Midtones Hue Concentration b、Highlights Hue Concentration a 和 Highlights Hue Concentration b。

## 色相旋转：每张图像调整两个色调区域

使用 Hue rotation 曲线，让同一色调区域内的颜色一起旋转。在 A 中，将 Shadows 和 White 分别引向不同的配色；在 B 中，独立调整 Midtones 和 Highlights。Rotation 旋转整个色相环，而前面的 Concentration 操作改变环上的色相间距。

<figure class="grade-demo">
<img src="../assets/demos/color-hue-rotation.webp" data-still="../assets/demos/color-hue-rotation-still.webp" alt="色相旋转：A 调整 Shadows 和 White；B 调整 Midtones 和 Highlights。" loading="lazy">
<figcaption>色相旋转：A 调整 Shadows 和 White；B 调整 Midtones 和 Highlights。</figcaption>
</figure>

DCTL 滑块：A 使用 Shadows Hue 和 White Hue；B 使用 Midtones Hue 和 Highlights Hue。Hue Fit 控制 Rotation 与 Concentration 在色调区域间的融合。每次调整后都应保留前面的工作，并重新观察完整图像。

## 尝试范围更广的创意调色

自行试用 Global Cₗ → Hue 和 Global Cₕ → Hue。它们用平滑权重旋转所有色调区域中的低彩度和高彩度颜色。将其与各色调区域的控件组合，可以探索更具风格的配色。
