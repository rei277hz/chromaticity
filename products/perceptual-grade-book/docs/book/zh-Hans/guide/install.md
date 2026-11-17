# 安装与连接

## Blender 扩展

[旧版开发 ZIP](../downloads/perceptual_grade-v1.23.2-20261101.zip)包含
Perceptual Grade 1.23.2，并非本手册介绍的 Next 产品。手册网站不提供 Next
扩展 ZIP。获得 Next 安装包后，请通过 Blender 的扩展偏好设置安装。

在着色器或合成器编辑器中选择 **添加 → 颜色 → Grade** 或 **Grade Stack**。
选中节点后，打开编辑器 N 面板中的 **Perceptual Grade** 侧栏。选中的 Grade
输出会显示 Linear 和 Tone 控件；Color 控件分为 J、C、Adaptance 和 Warp 面板。
编辑共享控件前，请在节点选择器中指定已有 Grade，或使用 **新建调色** 创建一个。

## 在着色器中连接材质

将 **Image Texture** 的 Color 输出连接到 Grade 的 Color 输入。把 Grade 输出连接到
需要调整的材质输入，例如 Principled BSDF 的 Base Color，并保持着色器连接到
Material Output。若要预览不受照明影响的图像，可把 Grade 输出连接到 Emission
着色器。

Image Texture 的 Color Space 应与源图像编码一致，以便 Blender 正确解码。整个节点
图使用场景当前支持的工作色彩空间；Next 支持 Linear Rec.709、Linear Rec.2020
和 ACEScg 场景空间。

## 在合成器中连接图像

在合成器中启用 **Use Nodes**。将 Image 或 Render Layers 的 Image 输出连接到
Grade Color，再把处理结果连接到后续操作或输出。添加 Viewer 分支，以便编辑时
检查结果。采样 Render Layers 前先渲染一次。

若要制作节点自有动画，请右键 Grade 节点并选择 **转换为节点自有调色**。这会将
当前设置复制到该节点。共享 Grade 和栈条目仍由数据块持有；详见[共享与复用调色](shared-grades.md)。
