# Grade Stack

**Grade Stack** 将有序的共享 Grade 合并为一个采样变换。当前 Next 中所有启用的
条目都从上到下正向执行；此版本的 Stack 不提供反向求解。

## 排列与编辑条目

使用 **添加调色** 创建已启用的空条目，再通过选择器指定共享 Grade，或用条目
中的加号按钮新建 Grade。使用条目控件可启用或旁路它、选定侧栏编辑目标、上下
移动或移除它。解除 Grade 关联会留下空条目；移除条目不会删除共享 Grade 数据块。
没有已启用 Grade 的 Stack 为恒等变换。

点击条目的编辑控件后，侧栏会显示该共享 Grade 的设置。修改会更新所有引用它的
普通 Grade 节点和 Stack 条目。若某一条目需要不同参数，请先创建独立 Grade。Stack
的成员关系和顺序属于节点；Grade 设置属于共享数据块。

## 整个序列共用一个 LUT

Stack 将所有已启用 Grade（包括每个 Linear 矩阵）计算到一个由 GPU helper 准备的
65³ LUT 中。编辑时可以先安装 33³ 预览，随后更新为最终 65³。预览采用最终网格
每隔一个顶点的坐标，GPU helper 分别计算两种分辨率。更新期间可暂时显示上一个
完整结果，但渲染和正常保存需等待当前的完整结果。

修改被引用的 Grade、条目启用状态或顺序都会改变采样函数。安装结果前必须匹配
当前设置签名。文件载入后及渲染前，Next 会协调派生 LUT。若准备失败，会显示
错误，并以保留 alpha 的洋红结果关闭调色输出。

Stack 在固定的内部线性 ACEScg／ACES 白点坐标中运行。场景坐标转换位于 LUT 两端，
所有条目则包含在 LUT 内。详见[场景工作空间](working-white.md)和[求值与插值](https://rei277hz.github.io/perceptual-grade/technical/en/theory/lut.html)。
