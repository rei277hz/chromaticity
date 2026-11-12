# 影调

> **保留版本：** 本使用章节及截图描述 1.23.2，仍滞后于最新模型。当前参考见[理解模型](../theory/structure.md)；这些控件并非 Next 未来的 Warp 实现。

保留 A 和 B 中完成的 Linear 调整。现在根据各自的目标塑造影调关系：A 增强反差，B 提高暗部的可读性。

## 塑造反差并提亮阴影

用相同的 Tone 地标实现不同目的。在 A 中压低较暗的影调并提亮较亮的影调，形成 S 形反差曲线。在 B 中将暗部和中间区域提亮，形成类似伽马的曲线，同时让白色和最亮高光尽量保持原有关系。

拖动 Before 波形上的地标，或沿水平方向移动它的曲线圆点，以确定应映射到该地标目标的输入影调。After 波形显示结果。将输入地标向右移，表示希望较高的输入亮度达到同一目标；向左移则表示希望较低的输入亮度达到该目标。曲线会平滑融合这些调整要求。

<figure class="grade-demo">
<img src="../assets/demos/tone-curve.webp" data-still="../assets/demos/tone-curve-still.webp" alt="A 用 S 形曲线增强反差；B 用类似伽马的曲线提亮暗部。" loading="lazy">
<figcaption>A 用 S 形曲线增强反差；B 用类似伽马的曲线提亮暗部。</figcaption>
</figure>

在 Resolve 中，Perceptual Grade DCTL 使用 Input Black Nits、Input Shadows Nits、Input Midtones Nits、Input White Nits 和 Input Highlights Nits 这五个地标。Remap Fit 改变曲线拟合方式。Reference Nits 设置漫反射白的校准值，Peak Anchor Nits 设置亮部锚点。

这些 Nits 输入描述的是具有指定明度的中性色。应查看生成的曲线与波形，不要期待曲线在每个地标上都被硬性固定。放置各亮度后，调整 Remap Fit，让过渡范围更宽，或更集中在地标附近。

## 在波形上比较 SDR 与 HDR

在示例 A 中，寻找暗部、中间调以及像纸张这样的漫反射白。SDR 图像通常会将这些区域聚集在参考白线下方或附近，亮部细节可能只占据参考白附近的一小段范围。

在示例 B 中，找到类似的漫反射表面，再观察更亮的光源、窗户或镜面反射。HDR 波形可以把亮部特征放在远高于漫反射白的位置，同时让表面和中间调保持较低。分别比较这些区域；最高亮度峰值不代表图像的平均影调。

![并排显示的 SDR 与 HDR 波形](../assets/screenshots/tone-waveforms.png)

<p class="figure-caption">A 显示 SDR 图像及其紧凑的影调范围；B 显示 HDR 图像、漫反射白与明显分离的亮部高光。请使用相同的波形刻度，并标出这些特征。</p>

参考白线为 \(j=1\)，也就是明度读数中的 \(J=100\)。默认 Reference Nits 为 203，因此该线代表 203 尼特的中性白。即使当前 Grade 使用较低的 Peak Anchor Nits，图表仍会延伸到 4000 尼特中性的明度。扩展的感知波形使用这一明度刻度；Resolve 的原生示波器则使用 Resolve 中选定的刻度。

这个共用刻度解释了为什么 A 中会有空余的高亮余量。不要为了填满它而抬高中间调。在 B 中，应让漫反射白与真正明亮的区域保持有用的间隔，而不要把最亮峰值当作普通白色。

继续保留已完成的曲线，进入 Color。
