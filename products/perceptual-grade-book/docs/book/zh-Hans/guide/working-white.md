# 场景工作空间

Next 的 Grade 参考白固定为 D65。Linear 面板以不可编辑的值显示
**Working White: D65**；当前产品版本不提供此项 Grade 设置。源白 xy 控件仍可用于
Stage 1 的创意校正。

节点会在场景 RGB 工作空间与内部调色坐标之间适配。支持的 Blender 场景空间为
**Linear Rec.709**、**Linear Rec.2020** 和 **ACEScg**。切换场景空间会更新外围转换
矩阵并协调派生节点图。不同空间下相同的 RGB 数字不代表相同颜色；若要保持色度学
等价，输入 RGB 也应由 Blender 正确转换。

普通 Grade 节点在原生 Tone／Color 节点图之前应用 Linear 矩阵。Grade Stack 在固定
的线性 ACEScg／ACES 白点坐标中采样完整序列，并在 LUT 两端转换场景坐标。LUT 采样白点
是实现边界，不会改变 Grade 固定的 D65 外观参考。

切换工作空间可能需要新的派生图数据。若准备或恢复失败，Next 会显示保留 alpha
的洋红错误结果，并阻止渲染，直到当前内核修复。LUT 坐标见[求值与插值](https://rei277hz.github.io/perceptual-grade/technical/en/theory/lut.html)，
输入解码及 Stage 1 控件见 [Linear](linear.md)。
