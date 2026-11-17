# Tone

Tone 将中性输入亮度映射到感知明度曲线。完成 Linear 后，再设置输入锚点及
漫反射白和峰值参考。

## 设置影调锚点

Tone 提供以尼特为单位的 Black、Shadows、Midtones、White 和 Highlights 输入值。
Black 映射为黑色；Shadows、Midtones 和 White 分别映射到相应的中性明度锚点；
Highlights 映射到已配置的峰值锚点。这些是柔和曲线锚点，不是硬截断，也不是
独立输出值。

根据图像安排这些输入值。SDR 图像的大部分影调可能位于漫反射白附近或以下。
对于 HDR，应区分漫反射表面与发光或镜面高光，不要把普通中间调推向最亮像素。
曲线 Fit 控制曲线接近控制点的程度，以及每个控制点影响相邻区域的范围。Peak
用于选择受支持的中性峰值目标之一。

共享 Grade 与 Stack 控件为静态。转换为 **Node-Owned Grade** 后，可为数值控件
制作动画，但离散的 Peak 选择除外。关键帧属于包含该节点树的 Action，并由该
节点树的所有用户共享。

## 检查曲线效果

在预期场景显示变换下检查 Grade 输出及最终图像。Tone 会改变 Color 接收的信号，
所以移动锚点后应重新检查选择性色彩调整。编辑 Stack 中选定的 Grade 时，可通过
Blender 的图像与 Viewer 显示比较效果。

[Tone 模型](https://rei277hz.github.io/perceptual-grade/technical/en/theory/tone.html)介绍平滑插值及其参考明度刻度。
