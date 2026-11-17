# 渲染与烘焙

着色器和合成器中的共享 Grade 与 Grade Stack 节点提供 **Bake** 操作。节点自有的
动画 Grade 不提供 Bake，因为其设置会随时间变化。

## 烘焙节点输出

选中受支持的 Grade 或 Stack 节点，按当前路线设置输出尺寸，然后点击侧栏中的
**Bake**。结果会发布到受管理、打包的 32 位浮点 RGBA Image，节点随后改用该图像。
烘焙内容来自原生节点树求值：Grade 使用 helper 图像内核，Grade Stack 使用完整
65³ LUT 节点图。

**Use Bake** 可在图像输出和实时节点输出间切换，同时保留图像关联。如果调色设置
或被跟踪的源数据改变，烘焙凭据会失效，节点返回实时输出，并禁用 Use Bake，直到
重新烘焙成功。也可以手动关闭 Use Bake，同时保留已关联图像。受管理的 Image 可
由多个节点共享；重新烘焙会更新所有读取者。

设置跟踪包含目标节点、已启用 Stack 条目和实时上游 Grade／Stack 节点中的 Linear、
Tone 及全部 Stage 3 控件。

可选的 Shader **Vector** 输入只控制烘焙采样。未连接时，使用记录的烘焙 UV 图，
Image 烘焙则使用当前活动渲染 UV 图。

## Image 与 UV 路线

对于单个普通静态 Image、未连接源坐标的逐点 Shader 图，采用 Image 烘焙：每个源
纹素对应一个输出像素。无源图像的 Shader 常量会烘焙为 1×1 图像。合成器烘焙保留
原生输出范围；常量使用场景画布尺寸。

若图中有连接的坐标、依赖表面的着色、多个源 Image，或上游受管理的 UV 烘焙，则
需要在网格上执行 UV 烘焙。UV 烘焙使用 Cycles，并要求活动 UV 图位于 0–1 区域且
互不重叠。Image 烘焙遵从 Scene 渲染引擎：EEVEE 使用私有正交渲染；Cycles 使用
所选 CPU 或 GPU 设备；Workbench 或未知引擎会回退到 Cycles CPU。UV 烘焙使用 Scene
选定的 Cycles CPU／GPU。若 GPU 设备不可用，会显示失败，不会静默切换设备。烘焙
helper 不修改 Scene 或用户偏好设置。

烘焙会明确拒绝 UDIM／平铺图像、影片与图像序列、多视图／多层源、Shader to RGB、
影片剪辑与 Mask、关联或动画中的缓存／Alembic 几何、缺失或重叠的 UV，以及不受
支持的节点图实例。UV 烘焙前应应用不受支持的拓扑修改器或形变修改器。完整路线
边界见[Next 烘焙策略](https://rei277hz.github.io/perceptual-grade/technical/en/development/next-policies.html#next-policy.bake)。

## 渲染就绪

Next 会在渲染前协调派生内核。只有当前设置签名对应的完整结果可用于渲染。交互时
可暂时显示之前的完整结果并标记 **Updating**；当前结果准备失败时，会显示保留
alpha 的洋红输出，并阻止渲染预检。Grade Stack 编辑时可先使用 33³ 预览，但最终
渲染需等待 65³。
