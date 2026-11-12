# LUT 采样实验：上界 128

本实验改变 LUT 的采样坐标，保持解析调色函数不变。比较固定 Rec.2020/D65、非负的原生 ACEScg/ACES 白点，以及固定 AP1 基色、重新归一化至 D65 的有符号坐标。实验独立于当前发布代码的 LUT 采样策略。

## 统计域与误差

令 \(\mathbf q\) 为进入 LUT 的精确颜色，用 Linear Rec.709/D65 表示。普通正向 Grade 的输入在**阶段 1 之后**；逆向往返测试的输入是正向 Grade 的结果；Stack 的输入是整个 Stack 的输入，其阶段 1 矩阵一起烘焙。

令 \(T_R\) 转换至 Rec.2020/D65，\(T_A\) 使用 Blender/OCIO 的原生转换至 ACEScg/ACES 白点。两个筛选条件为

\[
m_R(\mathbf q)=\mathbf 1\{T_R\mathbf q\in[0,10]^3\},\qquad
m_A(\mathbf q)=\mathbf 1\{T_A\mathbf q\in[0,128]^3\}.
\]

它们是独立的掩码，不是交集。像素可能参与其中一个或两个统计域；不在任何域内的像素不参与误差统计。掩码使用严格的 float64 比较，在测试任何候选方案之前确定，不受候选基色、曲线、上下界或近似输出影响。

令 \(F\) 为完整解析参考，\(\widehat F_g\) 为候选网格 \(g\) 的采样结果。场景误差仅对 \(m_R=1\) 的像素计算：

\[
e_R^{(g)}(\mathbf q)=\left\|T_R\left(\widehat F_g(\mathbf q)-F(\mathbf q)\right)\right\|_\infty.
\]

即三个场景线性 Rec.2020 通道中最大的绝对误差，不除以亮度或参考 RGB。RMS 是这些逐像素最大通道误差的均方根。

对每个包含 ACES 2.0 渲染及输出编码的变换 \(V_v\)，仅对 \(m_A=1\) 的像素计算

\[
e_v^{(g)}(\mathbf q)=\left\|V_v\!\left(\widehat F_g(\mathbf q)\right)-V_v\!\left(F(\mathbf q)\right)\right\|_\infty.
\]

四个输出为 SDR 100 nits Rec.709/BT.1886、SDR 100 nits P3-D65/sRGB、HDR 1000 nits P3-D65/PQ 和 HDR 1000 nits Rec.2020/PQ。ACES 创作白点为 D65，没有额外的查看曝光或 Look。**主排名使用编码后的 RGB 绝对误差**。同时报告实际发光 RGB 的 nits 误差、除以输出峰值 nits 的误差、亮度误差及 ΔE_ITP。

没有合格像素的分布为 null，不伪装成零误差。处于统计域内但超出候选 LUT 网格的像素仍参与统计，使用边界四面体外推。`coverage.csv` 分开记录统计域排除与网格外推的数量。

## 三种采样坐标

标准 ACEScg 使用 AP1 基色及 ACES 白点 \((0.32168,0.33767)\)，通过 Blender/OCIO 的 Bradford 方法与 D65 互相适应。本实验的 **AP1/D65** 保留 AP1 基色 xy，重新以 D65 \((0.3127,0.3290)\) 计算归一化基色矩阵；它不是标准 ACEScg 编码。

若 \(P\) 的列为基色 XYZ，\(\mathbf w\) 为归一化白点 XYZ，则

\[
N_{\mathbf w}=P\,\operatorname{diag}\!\left(P^{-1}\mathbf w\right),\qquad
T_D=N_{\mathrm{AP1},D65}^{-1}N_{709,D65}.
\]

如果把原生 AP1 的整个基底适应至 D65，会得到与原生 ACEScg 配合 Bradford 转换基本相同的 RGB 采样坐标，因此并不是独立的色域实验。

所有候选方案先把顶点转换回规范坐标，计算相同的 \(F\)，再把结果转换至采样坐标存储。三个 Grade 的工作白点仍为 D65、ACES 和 D50，独立于 LUT 基底。“非负”仅指原生 AP1 采样轴从零开始，输入与输出 RGB 均不裁剪。

原生 AP1 `[0,128]³` 在 Rec.2020/D65 中约达到 **−3.879…+131.879**，在固定基色 AP1/D65 中约达到 **−1.167…+129.167**。因此分别测试 −4/−8 和 −2/−4 下界；原生 AP1 下界为零。两个 D65 基底即使下界足够，也会有部分源立方体顶点超过固定的 +128 上界。`metadata.json` 给出矩阵及各通道极值。

## 曲线与选择

规格声明 150 个网格：两个生产策略对照及 148 个 +128 候选方案。初始筛选与局部细化记录在 `lut-domain128-screening.json` 和 `lut-domain128-refinement.json` 中；组合后的 `lut-domain128.json` 为规范 Buck2 实验。曲线包括 asinh、log1p、线性趾部接对数、幂函数，以及对 log1p 的归一化坐标施加幂变形。改变下界、负侧分配及曲线尺度，也测试仅两个负侧区间。原生 AP1 的全部 64 个区间用于非负侧。负侧分配均为偶数，保持 33/65 嵌套网格的共同零顶点。

普通 asinh/log1p/趾部曲线的正负分支在零点匹配一阶导数；幂变形仅为额外的采样位置实验，不全部声称零点可导。插值使用物理场景线性 RGB 的比例，不使用整形后的比例。

筛选固定采用每幅图 2,048 个像素。完整验证使用四幅 IMG 夹具中的全部 338,688 个存储像素，输入曝光为 −2、0、+2、+4、+6 档，即每个任务在掩码前有 1,693,440 个像素。夹具是既有采样数组，不是原 EXR 全分辨率图像。任务包括正向 Grade、逆向、逆向往返、全正向 Stack 及混合正逆向 Stack。三个 Grade 的完整参数保存在规格中。

对十个项目——场景 RGB 的 p99/RMS，以及四个编码输出各自的 p99/RMS——先取所有图像/曝光/任务案例中的最差值，再最小化相对当前 −2…+64 生产策略的最大比值。同分时按平均比值、网格名称排序。报告中的“最佳”是这些域、夹具、参数及完整验证入围方案中的实测选择，不是任意颜色与参数的全局最优保证。

## 实测结果

150 个网格筛选、12 个完整入围方案，在编码 RGB 目标下选择 **原生 ACEScg/ACES 白点、[0,128]、64 个正侧区间、κ = .003 且幂变形 p = .9 的 log1p 曲线**。顶点 \(i\in\{0,\ldots,64\}\) 的通道采样位置为

\[
x_i=\kappa\left[\exp\!\left(\left(\frac{i}{64}\right)^p\ln\!\left(1+\frac{128}{\kappa}\right)\right)-1\right],
\qquad \kappa=0.003,\quad p=0.9.
\]

范围内的连续索引为

\[
s(x)=64\left[\frac{\ln(1+x/\kappa)}{\ln(1+128/\kappa)}\right]^{1/p}.
\]

由地址确定下方单元索引，插值比例仍为线性 RGB 的 \((x-x_i)/(x_{i+1}-x_i)\)。范围外使用边界单元外推，不裁剪 RGB。33³ 预览取 65³ 网格的每隔一个顶点。

原生 Rec.2020/D65 → AP1 转换矩阵的系数非负，其 `[0,10]³` 通道最大值约为 10，因此这个原生 `[0,128]³` 网格包含**两个请求的统计域**。这些输入不需要负侧区间。这不是改变 Grade 的工作白点，也不限制有符号输出 RGB。

| 各基底中完整验证的最均衡方案 | 范围 | 曲线 | 负侧 / 正侧区间 | 均衡比值 |
|---|---|---|---:|---:|
| 原生 ACEScg/ACES 白点 | 0…128 | log1p，κ .003，幂变形 p .9 | 0 / 64 | **0.725347** |
| AP1/D65 | −2…128 | asinh，κ .01 | 2 / 62 | 0.868271 |
| Rec.2020/D65 | −4…128 | 线性趾部接对数，κ .003 | 8 / 56 | 0.875586 |
| 原生产 Rec.2020/D65 | −2…64 | log1p，κ .003 | 20 / 44 | 1.000000 |

| 各案例最差统计量 | 当前生产 | 选中的原生 AP1 |
|---|---:|---:|
| 场景 Rec.2020 绝对 RGB p99 | 0.073063413 | 0.041688502 |
| 场景 Rec.2020 绝对 RGB RMS | 0.018554004 | 0.010447717 |
| SDR 100 Rec.709 编码 RGB p99 | 0.008575175 | 0.005389426 |
| SDR 100 P3-D65 编码 RGB p99 | 0.007430241 | 0.004507332 |
| HDR 1000 P3-D65 编码 RGB p99 | 0.004731874 | 0.002988917 |
| HDR 1000 Rec.2020 编码 RGB p99 | 0.003490032 | 0.002195976 |

十个主指标均改善。场景 p99/RMS 约降低 42.94%/43.69%，四个渲染 p99 降低 36.83–39.34%；十项中最小改善为 27.47%。这些比值在新的统计域和曝光组合下比较当前策略，不与旧的未使用掩码的实验统计量混用。

曲线选择依赖误差目标。同一组入围方案中，**原生 AP1 的普通 log1p、κ = .01** 在显示线性 RGB/峰值 nits 目标下胜出，比值为 0.530634。它的合并场景与编码 p99 也更低，但幂变形曲线对分别加权的编码视图改善更均匀，尤其是 HDR Rec.2020 RMS。优先级不同，可以考虑不同曲线。

渲染指标会实质改变选择。原生 AP1 的 log1p、κ = .1 得到场景 RGB p99 **0.025908**，低于所选方案的 0.041689，但其最差编码 ACES p99 为 **0.035947**，超过所选 0.005389 的六倍。仅最小化场景 RGB 会偏向渲染误差明显更大的曲线。

仍有罕见大误差。选中方案的 HDR P3-D65 编码最大误差为 **0.184539**，当前方案为 0.190931；其 p99 为 0.002989。场景 RGB 最大误差为 0.126010，当前方案为 0.189842。完整表保留这些异常值与像素坐标。选择目标是 p99/RMS，不是最大误差。

![完整入围方案的误差权衡](../assets/illustrations/lut-domain128-errors.svg)

![各基底采样位置](../assets/illustrations/lut-domain128-placement.svg)

{{#include ../assets/fragments/lut-domain128-key.md}}

本书图表根据已记录的实验数据重新绘制为矢量图。domain-128 入围方案误差坐标在已发布报告中保留至小数点后八位；采样位置图中的两个对比轴依据文档化的采样公式重建。原始工程报告及其归档图表保持不变。[下载绘图源文件及所绘数据](../downloads/chart-sources.zip)。

[下载所选采样轴与分数](../downloads/lut-domain128-selection.json)。完整源码包含 `docs/engineering/lut-domain128/report.md`；单独提供的结果包包含全部 JSON/CSV、图表及指纹。1.21.0 采用普通原生 AP1 log1p κ = 0.01，按显示线性 RGB／峰值 nits 目标选择；上面的变形曲线是编码目标的实验优胜者。参见[当前生产采样规范](../theory/lut.md)。

## 通过 Buck2 复现

```sh
buck2 build //:lut_domain128_evaluation //:lut_domain128_report --show-full-output
buck2 test //:lut_domain128_math_test //:lut_domain128_smoke_test
buck2 test //:lut_domain128_full_result_test
buck2 test //:lut_domain128_confirmation_test
buck2 build '//:lut_domain128_evaluation[metrics]' \
  '//:lut_domain128_evaluation[coverage]' \
  '//:lut_domain128_evaluation[selection]' --show-full-output
```

规格为 `tests/blender/experiments/lut-domain128.json`，声明夹具哈希、Grade 的矩阵/白点/Tone/Color 参数、曝光、随机种子、任务、曲线及变体、分配、统计域、四个输出变换和入围规则。Buck2 跟踪数学源码、夹具、生成的翻译、Python 锁定文件和完整 Blender OCIO 快照；分析依赖不进入扩展。

输出包括 JSON/CSV 指标、计数、排名、逐案例完整记录、精确采样轴、求解器诊断、float32 顶点哈希及哈希清单。报告目标生成 Markdown 和两幅科学图。冒烟测试检查输出约定及各候选共用的掩码；完整结果检查器独立重建选择。数学测试检查两个 AP1 定义、立方体极值、掩码、零点嵌套及仿射插值/外推。

创作预览可使用锁定的分析环境和完整 Blender OCIO 快照：

```sh
python -m tools.experiments.lut_domain128 --tree . \
  --spec tests/blender/experiments/lut-domain128.json \
  --ocio-config /path/to/colormanagement/config.ocio --output-dir /fresh/results
python -m tools.experiments.check_domain128_result --results /fresh/results
python -m tools.experiments.report_domain128 --results /fresh/results --output-dir /fresh/report
```

烘焙耗时仅为观察值；输入指纹、采样轴、顶点与指标值是复现约定。当前创作沙箱因缺少 `/proc/self/exe` 无法启动原生 Buck2。直接运行已声明的 Python 动作及稀疏输入审计，不表示原生 Buck2 发布门禁已通过。本实验不涵盖原生 GPU/Metal 传输，也不评价被掩码排除的颜色。

## 生产方案的采用

**1.21.0** 采用 `AP1_ACES_neg0_pos128_n0_log1p0.01`：原生 ACEScg／ACES 白点 [0,128]，64 个正侧单元，普通 log1p κ = 0.01。编码 RGB 联合比值为 0.842753；显示线性 RGB／峰值 nits 的联合比值为 0.530634，是完整候选中的最佳值。场景 p99／RMS 为 0.038344395／0.009574135，编码显示最差 p99 为 0.004779925。这些是已记录的实验指标，生产实现另以独立 AP1／Bradford 参考和原生 Shader／Compositor 渲染验证。Grade 白点和解析调色模型保持不变。
