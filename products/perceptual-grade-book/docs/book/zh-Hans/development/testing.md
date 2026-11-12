# 测试与测量

> **历史实现说明：** 本章保留 1.23.2 的运行时、源码布局与验证范围。当前开发命令及支持的行为请以 [chromaticity](https://github.com/rei277hz/chromaticity) 中各产品的 README 为准。

## CPU 优化与 GPU 探索（1.22.0）

1.22.0 正式扩展使用 float64 CPU 求解器；以下为历史测量，1.23.0 已安装 GPU 路径见下一节。常规二维逆改用解析残差／雅可比，共享系数曲线计算，并对参考能量相关的 H–K 反解求导；二维阻尼法使用防抵消的显式解。正向函数、迭代上限、接受阈值和诊断容差保持不变。[完整方程](../../en/development/forward-inverse-math.html#analytic-regular-jacobian)统一维护在英文数学规范。

与随附 1.21.0 的测试专用冻结代码交错复测三次，独立 65³ 烘焙中位数如下：

| 操作 | 基线 | 优化后 | 比值 |
|---|---:|---:|---:|
| 一个逆 Grade | 6.177 s | 4.425 s | 1.40× |
| 正向→逆→正向 | 5.230 s | 4.514 s | 1.16× |
| 三个正向 Grade | 2.236 s | 2.206 s | 1.01× |

此共享主机的耗时波动明显，不能视为桌面保证。九组表格对比中，混合／全正向结果逐位相同，逆表最大绝对差为 \(1.49\times10^{-8}\)；所有渐进最终表均与独立完整烘焙逐位相同。80 项前后精度检查在每组 2,114 个照片／有符号／HDR／中性输入、四种白点及四种配置上运行，最大单样本复现误差增加为 \(7.21\times10^{-10}\)，原有尽力求逆失败仍完整记录。

[CPU 耗时 JSON](../downloads/cpu-solver-performance.json)／[CSV](../downloads/cpu-solver-performance.csv)、[精度](../downloads/cpu-solver-accuracy.json)、[导数检查](../downloads/inverse-jacobian.json)包含完整参数、环境和指纹。冻结基线只进入测试，不进入安装扩展。

```sh
buck2 test //:numerical_test_inverse_jacobian //:numerical_test_cpu_solver_accuracy \
  //:numerical_test_inverse_solver //:numerical_test_inverse_math \
  //:numerical_test_progressive_lut //:blender_test_grade_stack \
  //:blender_test_stack_editing
buck2 build //:cpu_solver_benchmark --show-full-output
```

独立 GPU 原型通过 Blender 自身的 `GPUShaderCreateInfo` 在运行时编译 Python 内的着色器源，不安装外部 GPU 二进制或包。每个调用求一个顶点，把常规二维逆、H–K／影调标量逆、完整 RGB Broyden 恢复及整个堆栈保留在设备上，每个阶段只回读一次。33³／65³ 使用不重叠顶点池；整个渐进过程只计算 274,625 个顶点，公共 float32 值逐位复用。参数纹理容量固定，短堆栈编辑可复用程序与采样器布局。

原型使用 float32，其 RGB 残差尺度为 \(\max(10^{-12},\lVert y\rVert_\infty)\)，设备阈值为 \(3\times10^{-6}\)。暗部必须保留相对精度；直接把 CPU 的 \(1+\lVert y\rVert_\infty\) 配上 float32 阈值，会忽略细小却可见的暗部变化。正式 CPU 的 \(2\times10^{-8}\) 诊断标准保持原样。设备标记只统计 RGB 恢复及未达到设备标准的点，不声称符合更严格的 CPU 标准。

Mesa llvmpipe **软件渲染器**上的三次温态完整渐进烘焙中位数为：逆 Grade 0.664 s、混合堆栈 0.432 s、全正向堆栈 0.216 s，对应同组 CPU 的 8.05×／12.66×／7.81×。冷首次使用含延迟驱动编译约 55.53 s；固定参数布局避免混合堆栈再次支付该开销。这些数据不能证明物理 GPU、Metal 或 Vulkan 的速度。逐点恢复到严格 CPU 标准的混合方案中位数约 4.86 s，不能达到十倍目标。此版本没有在节点中启用 GPU 烘焙。

四张 IMG_* 每张固定抽取 512 个像素，在 −6／0／+6 档、三种堆栈工作负载下复测。Rec.2020／D65 [0,10]³ 内统计绝对 RGB；AP1／ACES [0,128]³ 内统计四种 ACES 2.0 输出。两种独立掩码均固定于精确堆栈输入，落在二者以外的像素排除。GPU 算术、CPU LUT 与 GPU LUT 相对于完整 float64 参考的误差分别记录。该样本中，GPU LUT 最差用例的 RGB p99 变化约 +0.0204%，已报告显示 RGB p99 最大变化约 +0.0371%；不是任意 Grade 的误差保证。

[英文工程报告](../downloads/gpu-solver-exploration.md)、[GPU JSON](../downloads/gpu-solver-performance.json)、[耗时 CSV](../downloads/gpu-solver-performance.csv)和[照片误差 CSV](../downloads/gpu-solver-photographic-errors.csv)保留编译、首次使用、每次耗时、参数、设备、排除计数、所有分布及源／夹具／OCIO 指纹。

```sh
buck2 test //:gpu_solver_math
buck2 build //:gpu_solver_smoke --show-full-output
buck2 run //:gpu_solver_benchmark -- \
  --blender /absolute/path/to/blender \
  --output /absolute/path/to/gpu-results/gpu-solver-performance.json \
  --full-grid --progressive --repeats 3 --repair
```

增加照片指标时，另传 `--fixture-samples 2048 --analysis-pythonpath /absolute/path/to/locked-analysis-wheels`，提供与 Blender Python 匹配的锁定测试专用 PyOpenColorIO。入口使用工厂启动和独立源代码副本；默认拒绝软件设备，`--allow-software` 明确记录软件正确性运行。Buck 缓存结果不是新计时样本，需运行可执行测量入口取得新数据。GPU 需要有效 Blender GPU 上下文，不能直接在现有任意 Python 工作线程里调用；桌面交互、取消、渲染／保存和硬件集成仍需独立实现与验证。

本次执行的是锁定运行时的编写预览。GPU 独立数学检查通过 39 项，覆盖八种白点、Fit −2／0／6、窄积分、恒等、黑／中性／负值／HDR／照片输入；正式 CPU 与原生堆栈回归同样通过。本环境没有 Buck2，声明的原生 Buck 构建／依赖门禁及物理 GPU 测量仍需在支持的工作站执行。

## Metal 完整矩阵更新修复（1.23.2）

后续 Mac 日志显示一次着色器失败后转 CPU，确认 1.23.1 的异常策略已生效。
编译仍拒绝 `mat2`／`mat3` 秩一矩阵除以标量。现在两个完整更新都先在向量列上计算，
再构造矩阵；求解公式与策略不变。

算术夹具读取非零、不对称雅可比和带符号向量的每个更新列，检查实际位移平方、
小／大分母，以及二维／三维割线条件。集成夹具保留普通编译／计算异常和每上下文
一次回退的测试。仍运行下方的 `//:gpu_solver_math` 和 `//:gpu_baking`。
[验证数据](../downloads/gpu-metal-matrix-fix.json)记录本次检查、源指纹与软件渲染器范围。
这些运行验证软件 OpenGL 正确性，不代表物理 Metal 编译或新的硬件性能测量。

## Metal 着色器启动修复（1.23.1）

提供的 Mac 日志显示 `outerProduct` 未声明，随后普通 `Exception: Shader Compile Error`
逃出绘图回调，使每次重绘都重新编译。现在二维／三维 Broyden 秩一更新使用显式列构造。
GPU 启动与计算捕获普通异常，每个上下文只记录并缓存一次失败，再由计时器发布当前 CPU 结果。

算术夹具新增带符号、不对称向量的两个矩阵方向检查。集成夹具注入普通编译异常，检查
只尝试一次、保留调用栈、退出“正在准备”并安装当前 CPU LUT；计算错误注入也使用普通异常。
仍运行下方的 `//:gpu_solver_math` 和 `//:gpu_baking`。
[修复验证](../downloads/gpu-metal-startup-fix.json)保留计数、源指纹及软件渲染器范围。
物理 Metal 启动与性能仍需在 Mac 上验证；下方 1.23.0 计时／照片表保留原始源快照，
不是新的 1.23.1 计时。日志获取方法见[渲染指南](../guide/render-methods.md#gpu-启动错误与日志)。

## 已安装 GPU 烘焙（1.23.0）

正式实现位于 `model/gpu.py`、`model/gpu_shader.py`、`graph/gpu.py` 和 `graph/lut.py`。
非线性 LUT 自动选择可用的物理图形设备，侧栏报告实际后端。
`tools/experiments/gpu_solver.py` 现在只是工作站测量适配器，严格全网格 CPU 修复仅为可选实验。
[渲染指南](../guide/render-methods.md#自动-gpu-烘焙)说明选择条件、首次编译与保存／渲染回退。

```sh
buck2 test //:gpu_solver_math //:gpu_baking
buck2 build //:gpu_solver_smoke --show-full-output
buck2 run //:gpu_solver_benchmark -- \
  --blender /Applications/Blender.app/Contents/MacOS/Blender \
  --output /absolute/path/to/results/gpu-solver-performance.json \
  --full-grid --progressive --repeats 3 \
  --fixture-samples 2048 \
  --analysis-pythonpath /absolute/path/to/locked-analysis-wheels
```

`--repeats 3` 为每种工作负载重新计时三次，不更改反向迭代数或质量。
默认负载为单逆、正向→逆→正向和三个正向 Grade。程序创建与首次驱动／布局预热单独记录。
最终数值时间包含有限批次、上传／回读、标记顶点 CPU 修复、坐标转换与 float32 存储；
不含防抖、编辑器帧等待、图像打包／发布、导入或渲染。`--repair` 另测严格全网格 CPU 验证，
不是正式的标记顶点修复策略。Buck 缓存输出不是新的计时样本。

独立算术测试覆盖八个白点、曲线 Fit、负值／HDR／暗部输入及 float64 正向复现。
已安装路径使用真实 Blender GPU 对象测试自动选择、上下文、公共顶点逐位复用、
拒绝工作线程、标记修复、取消、绘图／定时发布、连续编辑、回退、原生输出和清理。
软件设备许可仅在夹具中开启，不改变安装用户的自动物理设备策略。

[集成报告](../downloads/gpu-baking-validation.md)、[检查与原生测量](../downloads/gpu-baking.json)、
[完整网格 JSON](../downloads/gpu-baking-performance.json)、[计时 CSV](../downloads/gpu-baking-performance.csv)
和[照片误差](../downloads/gpu-baking-photographic-errors.csv)保留实际范围。
照片掩码、四种 ACES 输出及参考语义不变；当前 GPU LUT 已包含标记顶点 CPU 修复。
仅 GPU 算术误差不含插值。float32 审计不保证所有未标记顶点满足 CPU 残差容差。

本环境只有软件图形设备，编写预览不能证明物理 GPU／Metal 耗时、十倍加速、真实桌面交互
或 Buck2 发布门禁。应在目标 Mac 上保留设备信息、冷启动成本及全部温态重复结果。

后续的 [+128 统计域实验](lut-domain-study.md) 分别使用场景 RGB 和 ACES 渲染 RGB 的独立掩码，加入原生 ACEScg/ACES 白点、固定 AP1 基色/D65 的采样方案，并扩展照片曝光范围。其规格、Buck2 目标及数据表独立于历史 −2…+64 实验。

## Grade 与堆栈编辑回归

通过相同的隔离 Blender 测试入口运行当前回归：

```sh
buck2 test //:blender_test_stack_editing //:blender_test_grade_stack \
  //:blender_test_working_white //:blender_test_shared_grade_undo
```

`test_stack_editing.py` 调用 `tests/blender/stack_editing/` 中的 53 个 pytest 用例。调色节点铅笔的新增检查覆盖着色器与合成器编辑器中的多个调色节点和堆栈，验证最多一个铅笔激活、切换目标、侧栏与关闭按钮的同步，以及不分配 Grade 数据。
Pytest 及其精确开发依赖记录在 `third_party` 中，不会打包进 Blender 扩展。
覆盖紧凑控件、共享修改、启用／反向、铅笔激活、重排时跟踪具体条目、旁路禁止编辑、
手柄拖动与取消、仅使用已安装 LUT 的示波器、过期烘焙拒绝、着色器／合成器 CPU
原生输出，以及当前格式的保存／加载／撤销／禁用／重新启用。

原有堆栈和工作白点测试继续检查调度、共享动画、负 RGB、Alpha 和坐标不变性。
其中的反向操作改为单条目堆栈，普通 Grade 始终正向且渲染方式保持独立；撤销测试也检查旁路。
`inverse_reference.py` 仅供数值测试与历史精度研究单独评估阶段 2、3，不提供反向节点。
[合并后的验证记录](../downloads/grade-stack-ui-validation.json) 区分实际的编写预览执行、
Buck2 发布门禁与桌面／GPU 检查。

## 渐进堆栈烘焙测量

```sh
buck2 test //:numerical_test_progressive_lut //:numerical_test_cube_native \
  //:blender_test_stack_editing //:blender_test_grade_stack
```

验证嵌套坐标、共享顶点逐位复用、总计只求值 274,625 个顶点、反向诊断计数、取消和两个分辨率的原生采样。Blender 用例检查预览发布、示波器刷新、连续拖动合并、删除节点和最终渲染同步。

Python 3.13.15、NumPy 2.5.3、单 BLAS 线程，每组重新烘焙三次的中位数如下：

| 操作 | 独立 65³ | 首个 33³ 预览 | 仅细化 | 渐进总耗时 |
|---|---:|---:|---:|---:|
| 三个正向 Grade | 1.016 s | 0.121 s | 0.860 s | 0.979 s |
| 一个反向 Grade | 4.247 s | 0.996 s | 3.766 s | 4.830 s |
| 正向 → 反向 → 正向 | 4.693 s | 1.090 s | 4.192 s | 5.282 s |

各列分别取中位数，可能不恰好相加。耗时不含导入、调度、Blender 图集发布及渲染，不是交互帧率或固定时限保证。虽然顶点数不增加，两轮求解仍可能带来额外开销；收益是更早显示预览。不能据此声称任意堆栈的最终烘焙均小于五秒。

九次细化所得的最终 65³ 表均与相同参数的独立完整烘焙逐位一致。33³ 预览的插值较粗，最终渲染／保存前会替换。此次耗时测试没有重新进行摄影夹具的显示误差实验。

[完整参数、环境和记录 JSON](../downloads/progressive-bake-performance.json) / [CSV](../downloads/progressive-bake-performance.csv)。在已准备的测试目录中复测：

```sh
python tools/testing/run_fixture.py --authoring-preview --tree . \
  --script tests/blender/benchmark_progressive.py \
  --output-dir /absolute/path/to/results --capture tests/blender/reports
```

默认每组运行三次，不复用完成的 LUT。此入口不替代 Buck2 发布门禁。

## 共享 Grade 回归检查

运行参数所有权和实际撤销/重做测试：

```sh
buck2 test //:blender_test_shared_grades //:blender_test_shared_grade_undo
```

测试使用真实 Blender RNA 和原生求值图，覆盖空选择框、首次编辑分配与取消拖动、跨编辑器传播、节点本地渲染方式与手柄焦点、独立副本、重命名、取消关联、保留未使用的数据、Grade 关键帧、当前格式节点识别，以及保存/加载/禁用/重新启用。撤销测试实际操作 Blender 撤销栈，检查共享编辑、分配、副本和取消关联。

`//:blender_test_white_and_render_ui` 渲染由着色器和合成节点共享的 Grade，并比较禁用扩展后的输出。已有渲染测试还检查原生保存/加载和打包 LUT 的持久化。选择框绘制测试验证 `template_ID` 的绑定；桌面交互和 GPU 渲染仍需在桌面环境检查。

## 工作白点验证

`//:blender_test_working_white` 检查八种 Grade 白点、三种场景 RGB 空间、矩阵换基与控制推导、矩阵动画、两个添加菜单项、示波器、当前格式保存／加载，以及切换场景空间后的普通／堆栈 LUT 复用。包含着色器／合成器与直接／正向 LUT／反向／堆栈路径的 24 次 CPU 原生渲染；1.15.0 通过 102 项检查。[下载原生测量](../downloads/working-white-native.json)。

工作空间不变性与 LUT 近似精度是两个问题：固定 LUT 坐标可以在不同场景空间保持同一个采样函数，但不代表该函数无插值误差。

<a id="inverse-and-stack-precision"></a>

## 反向与堆栈精度

使用 `//:numerical_test_inverse_math`、`//:numerical_test_inverse_solver`、`//:blender_test_grade_stack` 与 `//:blender_test_shared_grade_undo` 检查方程、节点、原生渲染、保存和撤销。`tests/blender/evaluate_working_white_precision.py` 现测量固定线性 Rec.2020／D65 LUT 边界，三个 Grade 分别使用 D65、ACES 和 D50，按正向→反向→正向执行。

较早的 1.15.0 Rec.709 测量从四个 IMG_* 图像各抽取 2,048 个像素，从原始线性 Rec.2020 坐标转换，不裁剪负值。混合堆栈的归一化 RGB 误差 p99 为 0.000371–0.001575，四组样本均低于三个独立 LUT。但个别像素误差可能显著更大：IMG_0472 的堆栈最大值为 0.082083，普通反向最大值为 0.206524。极端有符号颜色与外推同样存在大误差。合并 LUT 消除了中间插值，并不保证每个像素都更准确。

误差定义为 RGB 最大绝对误差除以 1 加参考 RGB 最大绝对值，不是感知色差或亮度百分比。普通反向的 274,625 个顶点中有 174 个近似求解点，混合堆栈中有 130 个；这是 LUT 存储与插值之前的复现诊断。[下载历史 1.15.0 完整测量与 Grade 参数](../downloads/working-white-precision.json)。源代码中的 `docs/engineering/working-white-validation.md` 给出全部表格和验证范围。CPU 原生查表、反向求根与插值分开测试；不声称已验证 GPU／Metal。

该历史精度运行的数值烘焙用时为普通反向 4.08 秒、混合白点堆栈 5.13 秒、全正向堆栈 1.05 秒，不含 Blender 发布和编辑防抖等待。这是单次测量，不保证任意参数、堆栈长度或机器都达到相同时限。

## LUT 采样与 ACES 2.0 显示误差

1.16.0 已将 LUT 替换为**固定线性 Rec.2020／D65、−4…+64 范围、16 个负侧／48 个正侧单元，正侧 asinh κ = 0.001**，用于全部 Blender 工作空间。独立实验比较了 50 种配置，包括固定 Rec.2020／D65、更小的负值范围和四类采样曲线。十种候选在四个 IMG_* 夹具的全部 338,688 个已存储像素上验证，其中四种还在输入曝光 −2 和 +2 档时复测。夹具来自原始 EXR 每隔十二行／列抽样，不是原始全分辨率图像的逐像素测试。

实验保留场景 RGB 误差，并在实际 OCIO ACES 2.0 输出变换之后计算绝对显示光的 ΔE_ITP：SDR 100 nits Rec.709、SDR 100 nits P3-D65、HDR 1000 nits P3-D65，以及 HDR 1000 nits Rec.2020，均使用 D65 创作白点。还记录亮度误差（nits）、编码通道误差，以及 ΔE_ITP 超过 1／2／5 的比例。显示变换会改变场景线性差异的可见程度，因此需要同时保留 RGB 和显示指标。

下表为原曝光下四个图像、五种普通／堆栈操作中最差用例的 p99 ΔE_ITP，使用全部已存储像素；它不是合并分位数，也不是最大单像素误差。

| ACES 2.0 输出 | 原 Rec.709 | 所选 Rec.2020 |
| --- | ---: | ---: |
| SDR 100 nits Rec.709 | 3.308 | 1.510 |
| SDR 100 nits P3-D65 | 3.683 | 1.617 |
| HDR 1000 nits P3-D65 | 3.938 | 1.726 |
| HDR 1000 nits Rec.2020 | 4.105 | 1.823 |

输入曝光 −2／0／+2 档时，所选方案在全部输出中的最差 p99 为 1.374／1.823／2.086，原方案为 2.998／4.105／6.385。+2 档时，一个 84,672 像素用例有五个像素超出 −4 边界（0.00591%）。原曝光最大单像素误差仍为 11.738 ΔE_ITP；这不是视觉无损变换，ΔE_ITP 1 也不是适用于所有观看条件的绝对可见阈值。

使用 `tests/blender/run_lut_study.py evaluate_lut_sampling --production --mode full --ocio-config /path/config.ocio --output /fresh/results` 可测量正式采样器。[下载正式实现的逐用例测量及元数据](../downloads/rec2020-production.json)。[正向／反向数学规范](forward-inverse-math.md)现维护在手册中。

Rec.2020、−4…+64 范围、16 个负侧单元、正侧 asinh κ = 0.001 的候选，将原曝光下最差用例的 p99 ΔE_ITP 从 4.105 降到 1.823，但归一化场景 RGB p99 从 0.003427 升到 0.004296；超过 ΔE_ITP 1 的最差用例比例也从 4.55% 升到 6.46%。12 个负侧单元的方案有较少的中等误差，但在 +2 档时 p99 较差。缩小负值范围会减少覆盖，仍可能发生外推。没有方案在所有指标上都更好；本次选择优先降低所测输出与输入曝光下最差用例的 p99，同时保留中等误差比例和越界统计。

正式实现的 Rec.2020 LUT 边界独立于 Blender 场景空间，通过两侧的色域／Bradford 矩阵进行转换；各 Grade 保留自身白点和调色函数。更换 LUT 采样坐标不应改变模型的基色、锚点或 Grade 含义。

源工具位于 `tests/blender/`，入口为 `run_lut_study.py`，另有 `evaluate_lut_sampling.py`、`lut_sampling.py`、`aces_metrics.py`、`test_lut_study.py` 和 `report_lut_sampling.py`。123 项检查覆盖采样、外推、场景空间换基、独立 ITP／PQ 计算与 OCIO 输出路径一致性。OCIO、Colour 和 Matplotlib 仅用于分析，不是扩展依赖。正式 Baker／Cube 求值复现了所选实验方案在原曝光下的汇总指标。独立采样器、冻结的解析模型夹具、Shader／Compositor 原生测试和工作空间不变性检查覆盖集成。这不是原生 GPU 测试，也不替代 Buck2 发布检查。[阅读选择方案时的原始英文报告（包含图表和复现步骤）](../downloads/lut-sampling-report.zip)，或[下载汇总数据](../downloads/lut-sampling-summary.json)。

保留 1.14.1 的历史[精度](../downloads/inverse-stack-precision.json)和[性能](../downloads/inverse-bake-performance.json)数据。其 RGB 基底与 Grade 白点设置不同，不能把误差直接作为 1.15.0 的前后对比。`tests/blender/benchmark_inverse.py` 可重复测量重新计算的数值烘焙；旧工程报告说明纯 Python 求解器的优化。


## 可复现 LUT 地址曲线实验

1.20.0 将 **82 种网格**的比较声明为 Buck2 实验。`tests/blender/experiments/lut-shaper.json` 包含照片路径／SHA-256、三个 Grade 的矩阵与白点及全部 Tone／Color 参数、五种工作负载、曝光、随机种子、曲线族／尺度、负侧单元分配、四种 ACES 输出及选择规则。旧 −4…64 网格作为测量基线；匹配尺度、独立负尺度、局部细化三批作者测试的规格也保留。

```sh
buck2 build //:lut_shaper_evaluation //:lut_shaper_report --show-full-output
buck2 test //:lut_shaper_experiment_test
buck2 test //:lut_shaper_full_result_test
buck2 build '//:lut_shaper_evaluation[selection]' \
  '//:lut_shaper_evaluation[metrics]' '//:lut_shaper_evaluation[metadata]' \
  '//:lut_shaper_evaluation[full]' --show-full-output
```

修改主规格后，Buck2 会重新计算受影响结果。测试专用 `bpy` 提取完整的 Blender OCIO 配置与资源，使用锁定的 PyOpenColorIO 2.5.0；不依赖桌面安装路径或环境 `OCIO`。PyOpenColorIO、Colour 和 Matplotlib 不进入安装扩展。配置／资源、源代码、依赖和输入指纹都写入元数据。NumPy 加载前将 BLAS／OMP 固定为一线程；数值指标可复现，耗时和平台字段不要求逐字节一致。完整比较比单次 LUT 烘焙慢很多，因为每种候选均需计算大量像素和四种显示输出；Buck2 会缓存未变化的声明输入。

四张 IMG_* 共 **338,688 个存储像素**，取原 EXR 每十二行／列。全部像素测试 −2／0／+2 档，共每种工作负载 1,016,064 个输入。普通正向 Grade 的 Stage 1 留在 LUT 外；单条目逆、逆往返及两种三条目 Stack 均将全部矩阵与白点连接计入解析函数。逆参考包含有界求根和所选分支，不假设任意分级具有精确往返。采样值为 float32，参考计算为 float64。独立原型通过 `searchsorted` 和实际线性 RGB 距离作四面体插值，另行验证生产采样器与其一致。

筛选每张照片 2,048 个固定样本。四个平衡目标最佳、两个显示最佳、两个绝对 RGB p99 最佳，加基线与明确必测候选进入完整验证，重复候选只计一次。完整阶段保留全部存储像素，也记录排除筛选样本后的留出分布。“最佳”仅指完整验证候选中的最佳，非所有可能曲线／Grade 的全局最优。

绝对 RGB 每像素误差为 \(e_{\mathrm{RGB}}=\max_j|\hat r_j-r_j|\)，分别在 Linear Rec.709、Linear Rec.2020、ACEScg 测量。RMS 是这些每像素最大通道误差的均方根，不是合并三个通道的 RMS。还保留归一化误差、分母下限 0.001 的相对误差。显示使用 D65 创作白的 SDR 100 nits Rec.709／BT.1886、SDR 100 nits P3-D65／sRGB、HDR 1000 nits P3-D65／PQ、HDR 1000 nits Rec.2020／PQ；P3 HDR 使用相同 OCIO ACES 2.0 内置输出，即使 Blender UI 不列出该组合。记录绝对光 ΔE_ITP、亮度 nits、编码通道差、显示 RGB nits 差以及 ΔE 大于 1／2／5 的比例。

统计先按**照片 × 曝光 × 工作负载**计算，再取最差；不合并不同照片的像素分位数。预先声明的目标最小化十项相对于旧网格的最大比值：四项显示 p99、三项绝对 RGB p99、三项绝对 RGB RMS。比值大于 1 表示退步；并列按最差显示 p99、名称排序。此比值规则要求基线误差非零，因此不适用于只有恒等分级的测试。最大误差等非排名指标仍完整保留。

输出包括 `metadata.json`、`selection.json`、两阶段排名、每网格 `screen/`／`full/` JSON、`metrics.csv`、`ranking.csv` 和所有非缓存输出的 `manifest.json`。保留范围外计数、边界、最差像素位置、留出分布和求解诊断。报告目标生成两幅科学图与 `report.md`。缓存是构建中间产物，不进入下载报告。英文[完整说明](../../en/development/testing.html#reproducible-lut-shaper-experiment)给出作者测试的 Python 命令。

打包测量由三批作者测试组成；所有数值输入和目标一致，批次元数据保留，最终严格重建主规格的全局候选。未宣称 Buck2 执行通过：本环境缺少 `/proc/self/exe`，Buck2 无法启动。声明／输入审计、Python 生成入口、数值测试和结果验证已通过；原生 Buck2 构建／测试门禁需要在正常支持的主机执行。


### 1.20.0 记录结果

82 种网格筛选出 12 个完整验证候选。在强制 −2…64 范围内，平衡选择为 **log1p，20 个负侧／44 个正侧单元，正侧 κ = 0.003，匹配负侧 κ = 0.0019620422371104795**。原 −4…64 网格的联合目标仍更好。

| 最差用例指标 | 原 −4／16 asinh .001 | 所选 −2／20 log1p .003 | 显示优先 −2／16 log1p .001 |
|---|---:|---:|---:|
| SDR100_Rec709 p99 ΔE_ITP | 1.847365 | 2.183193 | 1.706017 |
| SDR100_P3D65 p99 ΔE_ITP | 1.871935 | 2.245625 | 1.827746 |
| HDR1000_P3D65 p99 ΔE_ITP | 2.075527 | 2.501072 | 1.922715 |
| HDR1000_Rec2020 p99 ΔE_ITP | 2.085620 | 2.514019 | 2.063685 |
| Linear Rec.709 absolute RGB p99 | 0.03051798 | 0.02558292 | 0.02650314 |
| Linear Rec.709 absolute RGB RMS | 0.01025971 | 0.01265570 | 0.01359318 |
| Linear Rec.2020 absolute RGB p99 | 0.02595036 | 0.02195883 | 0.02310018 |
| Linear Rec.2020 absolute RGB RMS | 0.00865254 | 0.01107384 | 0.01191678 |
| ACEScg absolute RGB p99 | 0.02521603 | 0.02129752 | 0.02237522 |
| ACEScg absolute RGB RMS | 0.00842654 | 0.01074439 | 0.01156180 |
| Balanced ratio to previous grid | 1.000000 | 1.279837 | 1.377258 |
| Worst fraction outside cube | 0.005905% | 0.184240% | 0.184240% |

所选绝对 RGB p99 降约 16.2%，但最差显示 p99 升约 20.5%、RGB RMS 升约 23.4%。联合最大比值为 1.279837，表示相对于旧网格仍有退步。若只优先显示 p99，16 个负侧单元、正侧 κ = 0.001 的 log1p 更好，而 RGB RMS 更高。普通正向 Grade 在所选曲线下改善；Stack／逆用例决定总体折中。

非负 ACEScg [0,64]³ 的最小蓝通道约 −1.939416，与给出的计算吻合，但正向最大值约 +65.939415。更关键的是，+2 档有符号照片的 Stack 查询低至 −4.902344；该用例有 137 个像素低于 −2，只有五个低于 −4。各工作负载最差范围外比例分别为 0.184240% 与 0.005905%。全部范围外像素仍计算每项指标并使用连续边界外推，没有裁剪或删除。因此，源空间角点范围不足以证明收窄范围后分级更准。

![最终候选的显示与 RGB 误差](../assets/illustrations/lut-shaper-errors.svg)

![原网格与所选网格采样](../assets/illustrations/lut-shaper-placement.svg)

{{#include ../assets/fragments/lut-shaper-key.md}}

这些矢量图使用原始地址函数报告档案中已记录的入围分数及精确采样轴重新绘制，不重新运行测量。[下载绘图源文件及所绘数据](../downloads/chart-sources.zip)。

[所选网格与摘要](../downloads/lut-shaper-selection.json)；[完整 JSON／CSV 结果、图、输入元数据与当前源代码复测](../downloads/lut-shaper-report.zip)。源包含全部照片样本与规格。原生 CPU Shader／Compositor、33／65 嵌套和半精度缓冲运输另行验证，不宣称 GPU／Metal 精度已通过。

## 原生 AP1 生产 LUT（1.21.0）

当前方案为原生 ACEScg／ACES 白点、上界 1024、64 个正侧单元、普通 log1p κ = 0.01。地址函数与采样空间由实验章节在其 +128 候选之间选定，上界是之后提高的，因此该选择证据覆盖的是地址函数而非 1024 域。[实验章节](lut-domain-study.md)记录其显示线性 RGB／峰值 nits 选择依据。历史表格保持原始参数。

独立 AP1 参考分别构建原色矩阵、Bradford 适应、采样轴和物理插值，解析夹具保持冻结。测试包含负值／HDR 外推、八个 Grade 白点、三个场景空间、Shader／Compositor 渲染、Alpha、当前格式保存／重载／撤销、共享 Grade、33³／65³ 顶点逐位复用，以及 Compositor 基础值／边差分图像的半精度缓冲。英文[测试命令](../../en/development/testing.html#native-ap1-production-lut-1210)给出 Buck2 门禁；原生 CPU 与缓冲模拟器不代表 GPU／Metal 验证。
