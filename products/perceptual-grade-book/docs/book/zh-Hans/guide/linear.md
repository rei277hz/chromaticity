# Linear

Linear 在非线性的 Tone 与 Color 阶段之前执行精确矩阵变换，为后续调色建立
合适的曝光和色彩平衡。

## 曝光与源白

**Exposure** 以档为单位；+1 会使场景线性 RGB 加倍。先设置合适的信号范围，
但不要用它抹去高光细节。源白 x、y 控件指定 Stage 1 适应的色度坐标。点击
**Match White** 可将源白恢复为 D65。

当前 Next 版本显示的 Working White 固定为 D65。Linear 还提供青红和黄蓝方向的
**Balance**、**Spread** 和 **Heading**。Balance 改变对立颜色的相对曝光；Spread
改变该方向相对白点的位移；Heading 在 xy 平面旋转方向。这些控件共同形成 Grade
矩阵。

校正白平衡时，选择在目标光照下拍摄的中性表面。调整源白直至该表面呈中性，
再检查其他颜色与肤色。若中性色正确而其他表面仍不协调，可使用 Balance、Spread
或 Heading 调整整体关系。它们作用于整幅图像，并非仅修改采样色块。

Blender 按 Image Texture 的 Color Space 设置解码图像。调色前请确认此设置；
错误的传递函数或色域无法靠 Grade 可靠补偿。节点会处理场景工作色彩空间适配；
Next 支持 Linear Rec.709、Linear Rec.2020 和 ACEScg。

普通 Grade 在原生非线性阶段之前以精确矩阵计算 Stage 1。在 Grade Stack
中，完整的有序变换会一起采样。关于采样坐标与场景 RGB 的关系，见[工作空间](working-white.md)。
