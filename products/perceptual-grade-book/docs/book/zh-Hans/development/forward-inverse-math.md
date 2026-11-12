# 完整正向与反向数学规范

本章并列保留当前参考规范与 **Perceptual Grade 1.23.2** 的推导。当前解析权威是 `libraries/perceptual-grade-reference`：6.5 节说明其阶段 3，第 20 节说明其逆与 Stack oracle。6.3–6.4 以及 9–19 节保留历史控件、带符号提升／回退策略与部署的逆向机制，除非明确标注当前对比。这些历史配置不实现修正后的 Warp 顺序。

方程假定调色参数与观察条件固定。逆向不要求能表示为滑杆设置。方程描述实数运算，数值分支与实现配置另行说明。先做代数归约、再做标量或二元求根在这里称为**半解析逆**；该术语描述保留的生产逆，而非当前参考搜索，也不主张通用闭式逆或全局收敛。

固定正参考能量与正请求明度时，独立 H–K 保护是一一映射，其唯一逆由有界严格单调标量方程给出。保留的生产逆把它嵌入阶段 3 的二元求解，再撤销 Tone 与阶段 1。当前参考则对每个候选求值完整正向映射：H–K 修复先于 Scale，RGB 导出处仅执行立方体包含。第 20 节规定这一搜索。

完整调色仍可能有多个原像。黑点裁剪、奇异矩阵、带符号扩展、回退选择、有限精度以及创造性的阶段 3 折叠都需要明确的策略。定参考的保护逆本身并不足以证明完整调色的单射性。

## 1. 源码契约与实现配置

下表源码名属于保留的 1.23.2 推导。当前参考入口是 `libraries/perceptual-grade-reference` 下的 `src/model.py`、`src/grading.py`、`src/inverse.py` 与 `src/stack.py`。

| 源码 | 相关函数 |
| --- | --- |
| `model/linear.py` | `safe_source_white`, `rgb_to_xyz`, `adaptation`, `references`, `directional_matrix`, `matrices` |
| `model/tone.py` | `viewing`, `response`, `unresponse`, `eccentricity`, `kernel_integral`, `saturation_gain`, `Model.remap`, `Model.attributes`, `Model.core`, `Model.apply` |
| `model/color.py` | `chroma_drivers`, `chroma_crossover`, `Model.stage2_with_ja`, `Model.weights`, `Model.drivers`, `Model.adjustments`, `hue_concentration`, `Model.stage3`, `hk_energy`, `_project_hk_energy`, `Model.decode`, `Model.apply` |
| `model/curves.py` | `integral_jet`, `weights_jet`, `jets`, `coefficients`, `Table`, `BasisTable`, `ToneModel`, `ColorModel` |
| `graph/tone.py`, `graph/color.py`, `graph/curve_tables.py` | 原生图等价实现与系数表求值 |
| `Perceptual-Grade.dctl` | `pg_model`, `pg_linear`, `pg_stage2_appearance`, `pg_drivers_ja`, `pg_attributes`, `pg_hue_concentration`, `pg_stage3_ja`, `pg_hk_energy`, `pg_project_energy`, `pg_decode_reference`, `pg_core`, `pg_nonlinear_eval` |

共享系数机制在明确标注处与当前参考进行对比。第 18 节保留历史半解析逆和 Stack 组合，第 19 节保留其工作白点与 LUT 边界契约。[采样章节](../theory/lut.md)给出当前参考／共享输入修复与采样规则；[测试](testing.md)记录历史实验与其适用范围。

在实现逆变换时，先选定要反转的前向求值器：

1. **当前独立参考：** 使用 6.5 节的阶段 3 与第 20 节的完整正向求值。
2. **历史标量表：** 使用第 14 节各配置实际存储的系数表、端点 jet 与规则。
3. **保留的 DCTL／原生内核：** 保留其控件、顺序、预处理、精度、有效性检查与旁路规则。

这些配置在数学设计与算术上都有差异。与独立 Python 参考吻合不能作为已完成 Resolve 或 Blender 渲染测试的证据。反演前应选定所需的正向函数。

保留的 DCTL 顺序定义第 9–19 节的历史带符号提升／回退契约，不应替代 6.5 节的当前参考顺序。RGB／XYZ 适配使用选定的调色基底；可选的诊断、示波器与显示渲染不属于调色函数。

## 2. 符号、空间与单位

向量按列处理。除非另有说明，两个锥响应三元组之间的除法、向量的绝对值，以及作用在向量上的标量响应函数都按分量逐一进行。所有普通对数都指自然对数。三角函数参数以弧度为单位；存储的 Hue 与 Heading 控件使用角度。

| 符号 | 定义 |
| --- | --- |
| \(x,y\in\mathbb R^3\) | 输入的场面线性工作 RGB 与输出；允许出现负值与大于 1 的值 |
| \(x_1=M_1x\) | 经过阶段 1 之后的工作 RGB |
| \(P,P^{-1}\) | 工作 RGB 到 XYZ 以及 XYZ 到 RGB 的矩阵 |
| \(W_s,W_d\) | 源白点与目标白点的 XYZ，二者都归一化到 \(Y=1\) |
| \(A\) | CAT16 的 XYZ 到锥响应矩阵 |
| \(Q=\operatorname{diag}(1/(AW_d))AP\) | 工作 RGB 到归一化锥响应的矩阵 |
| \(n=Qx_1\) | 源特定舍零之前的归一化锥响应三元组 |
| \(q=(H,a,b)\)；\(z=a+ib\) | 外观坐标；\(z\) 是同一对实数的复数表示 |
| \(C=\lvert z\rvert\)；\(h=\arg z\) | 实际的 modCAM16 彩度与色相；当 \(C=0\) 时色相无意义 |
| \(J=J_A\) | 消色差外观明度，独立于 \(H,C\) 携带 |
| \(s=75C/J\) | modCAM16 饱和度；在纯黑处无定义 |
| \(p_d=2\)，\(s_0=35\)，\(C_n=2\) | 固定的分类器指数、饱和度中点与绝对彩度中性淡出尺度 |
| \(r_s=s_0/75=7/15\) | 把 \(J\) 换算到分类器边界的比值 |
| \(v_n(C)\)，\(\omega(J,C)\) | 中性可见度与高饱和隶属度，定义见 6.2 节 |
| \(H=J_{\mathrm{HK}}\) | 带符号 H–K 明度；只有 \(J\ge0\) 时才有 \(H=\sqrt{J^2+66C}\) |
| \(k_{\mathrm{HK}}=66\) | H–K 明度平方的固定彩色贡献 |
| \(q_0,q_2,q_3,q_g\) | 阶段 1 之后、阶段 2 之后、阶段 3 的原始请求，以及经过防护的阶段 3 输出 |
| \(J_i,C_i,z_i\) | 下标 \(i\) 处对应的消色差明度、彩度与复数对 |
| \(E_r\) | 非负保护参考：当前参考使用 \(\max(J_2\lvert J_2\rvert,0)\)；历史正分支使用 \(J_2^2\) |
| \(E=J_g^2\) | 防护输出能量，直接带入外观解码 |
| \(X=H_3^2\)，\(D=X-66C_3\) | 原始请求的明度平方与原始请求的消色差能量 |
| \(U=H_g^2=E+66C_g\) | 经过防护的明度平方 |
| \(R_w,P_w\) | 以尼特为单位的有效参考亮度与峰值亮度 |
| \(\mathcal E(n)\) | 归一化锥响应的外观编码；也可直接返回 \(J\) 或 \(J^2\) |
| \(\mathcal D(q,E)\) | 使用给定能量把外观普通解码为归一化锥响应；它**不**施加防护 |
| \(\Phi=\mathcal E\circ Q\) | 在其有效分支上的工作 RGB 外观编码 |
| \(T,S,\mathcal R_{E_r}\) | 阶段 2、原始阶段 3，以及固定参考的 H–K 防护 |

\(H,J,C\) 是外观坐标的值，不是尼特，也不是对数 RGB 码值。分级用的 \(a,b\) 半径为 \(C\)；它们不是经过对数压缩的 CAM16-UCS 对。

当前参考携带 `State(q, energy)`，其中 \(E_s=J_A|J_A|\)，故 \(J_A=\operatorname{sign}(E_s)\sqrt{|E_s|}\)。令 \(b=\sqrt{66C}\)：\(J_A\ge0\) 时带符号明度为 \(H=\sqrt{J_A^2+b^2}\)，否则为 \(H=2b-\sqrt{J_A^2+b^2}\)。Tone 携带缩放后的能量，保护接收冻结的 Tone 后值，不能通过舍入后的 \(H_2^2-66C_2\) 相减重建参考。旧的 `Appearance(H,a,b,J)` 与相减式探针约定属于下文保留的历史配置。

## 3. 阶段 1：精确的矩阵构造

### 3.1 工作原色与白点

定义

$$
\operatorname{XYZ}(x_c,y_c,Y)
=Y\left(\frac{x_c}{y_c},1,\frac{1-x_c-y_c}{y_c}\right)^T.
$$

对于工作原色的色度 \(p_R,p_G,p_B\)，令

$$
P_0=[\operatorname{XYZ}(p_R,1)\;\operatorname{XYZ}(p_G,1)\;\operatorname{XYZ}(p_B,1)],
\qquad s=P_0^{-1}W_d,
\qquad P=P_0\operatorname{diag}(s).
$$

独立的参考实现支持以下 RGB 空间。Blender 节点则使用第 19 节所规定的固定分级基与所选白点，与其场景 RGB 空间无关：

| 空间 | 红 \(xy\) | 绿 \(xy\) | 蓝 \(xy\) | 白点 \(xy\) |
| --- | --- | --- | --- | --- |
| Linear Rec.709 | \((.64,.33)\) | \((.30,.60)\) | \((.15,.06)\) | \((.3127,.3290)\) |
| Linear Rec.2020 | \((.708,.292)\) | \((.170,.797)\) | \((.131,.046)\) | \((.3127,.3290)\) |
| ACEScg | \((.713,.293)\) | \((.165,.830)\) | \((.128,.044)\) | \((.32168,.33767)\) |

对于其他 DCTL 空间/白点选择，应始终如一地使用其选定的 \(P,W_d\)；不要悄悄替换成 Rec.709 或 D65。

### 3.2 源白点预处理与色适应

$$
A=\begin{bmatrix}
.401288&.650173&-.051461\\
-.250268&1.204414&.045854\\
-.002079&.048952&.953127
\end{bmatrix}.
$$

源码会把源白点色度投影到一个容许多边形内。首先把每个坐标钳制到 \([0,.9]\)。要求 \(y_c\ge.002\)，并且对每一行 \((A_{i1},A_{i2},A_{i3})\) 都有

$$
(A_{i1}-A_{i3})x_c+(A_{i2}-A_{i3})y_c+A_{i3}
\ge .002\sqrt{(A_{i1}-A_{i3})^2+(A_{i2}-A_{i3})^2}.
$$

如果钳制后的点落在这个凸多边形之外，就按 \(xy\) 上的欧氏距离把它投影到边界上最近的点。Python 模型对非有限的源坐标用 D65 替代；请按所选宿主一致地拒绝或净化非有限参数。这属于参数预处理，不是逐像素的颜色操作。

用得到的 \(W_s\)，

$$
M_{\mathrm{CAT}}=A^{-1}\operatorname{diag}\left(\frac{AW_d}{AW_s}\right)A.
$$

当源与目标 \(xy\) 的两个坐标之差都小于 \(5\times10^{-8}\) 时，Python 的重置路径使用精确恒等。在复现某个宿主时，要保留其有效的预处理参数与重置标志。

### 3.3 方向性控制

把 Rec.709 的红、蓝原色从 D65 适应到 \(W_d\)，把它们的 XYZ 转换为 \(xy\)，再从目标白点色度 \(w_d\) 处取各自位移的 30%。称这些参考点为 \(p_r,p_b\)。

对每个方向性控制 \(i\in\{r,b\}\)，设内部 Balance \(b_i\) 以档（stop）为单位、Spread \(s_i\) 以百分比为单位、Heading \(\vartheta_i\) 以度为单位，

$$
p_i'=w_d+(1+s_i/100)R_{\pi\vartheta_i/180}(p_i-w_d),
$$

$$
V_i=\operatorname{XYZ}(p_i,1),\qquad
V_i'=2^{b_i}\operatorname{XYZ}(p'_{i,x},\max(.01,p'_{i,y}),1),
$$

$$
\mathsf B=[W_d\;V_r\;V_b],\qquad
\mathsf B'=[W_d\;V_r'\;V_b'],\qquad
M_{\mathrm{dir}}=\mathsf B'\mathsf B^{-1}.
$$

DCTL 在提供这些内部 \(b_i\) 之前，会先对显示出来的 Balance 控件取负。不要再次对已存储的内部模型值取负。

对于以档为单位的曝光 \(e\)，

$$
\boxed{M_1=2^eP^{-1}M_{\mathrm{dir}}M_{\mathrm{CAT}}P,\qquad x_1=M_1x.}
$$

如果所有方向性控制都为零，源码使用精确恒等的方向矩阵。曝光与这些矩阵可交换。

## 4. 外观编码与普通解码

### 4.1 观察常数

解析参考实现通过一个平滑且有界的映射推导这两个有效值，而不是整数舍入。对于下界 \(\ell\)、上界 \(u\) 与五次缓动 \(e(x)=x^3(6-8x+3x^2)\)，

$$
\operatorname{floor}_{\ell}(v)=\begin{cases}\ell,&v\le\ell\\ \ell+e(v-\ell),&\ell<v<\ell+1\\ v,&v\ge\ell+1\end{cases}
\qquad
\operatorname{cap}_{u}(v)=\begin{cases}v,&v\le u-1\\ u-e(u-v),&u-1<v<u\\ u,&v\ge u\end{cases}
$$

$$
R_w=\operatorname{cap}_{1000}\!\left(\operatorname{floor}_{48}(R_{\mathrm{input}})\right),
\qquad
P_w=\operatorname{cap}_{10000}\!\left(\operatorname{floor}_{2R_w}(P_{\mathrm{input}})\right).
$$

两个映射在边界内一个单位以上时严格等于恒等，在边界外严格等于边界值，并且在接合处一阶、二阶导数都连续。1.23.2 版的 DCTL 则舍入到最近的尼特；这会在每个半尼特处产生一尼特的台阶，也正是带小数的 Reference Nits 输入在两种实现之间表现不同的原因。参考实现请使用平滑形式。

DCTL 的峰值菜单首先从 500、1000、2000、4000 尼特中选择，若所选值不满足参考亮度的约束，则把它提升到该菜单中满足约束的受支持值。把**有效的** \(R_w,P_w\) 当作前向与逆向共享的配置；不要把菜单索引重新解释为尼特值。

定义

$$
L_A=.1R_w,\quad k=(5L_A+1)^{-1},
$$

$$
F_L=.2k^4(5L_A)+.1(1-k^4)^2(5L_A)^{1/3},\qquad
\gamma=.943019577159.
$$

锥响应及其逆为

$$
\rho(n)=\operatorname{sgn}(n)\frac{400(F_L|n|)^{.42}}{27.13+(F_L|n|)^{.42}},
$$

$$
\rho^{-1}(s)=\frac{\operatorname{sgn}(s)}{F_L}
\left(\frac{27.13|s|}{400-|s|}\right)^{1/.42},\qquad |s|<400.
$$

令 \(A_w=3.05\rho(1)\)，\(Q=\operatorname{diag}(1/(AW_d))AP\)。

### 4.2 编码归一化锥响应

对于 \(s=\rho(n)\)，定义

$$
A_c=2s_R+s_G+.05s_B,
$$

$$
a_o=s_R-s_G+(s_B-s_G)/11,\qquad
b_o=(s_R+s_G-2s_B)/9.
$$

若 \(s=0\)，返回精确的黑色 \(H=J=C=a=b=0\)。否则要求 \(A_c>0\) 且结果有限。然后

$$
J=100(A_c/A_w)^\gamma,\quad r_o=\operatorname{hypot}(a_o,b_o),\quad
h=\operatorname{atan2}(b_o,a_o),
$$

$$
\begin{aligned}
\epsilon(h)={}&1-.0582\cos h-.0258\cos(2h)-.1347\cos(3h)+.0289\cos(4h)\\
&-.1475\sin h-.0308\sin(2h)+.0385\sin(3h)+.0096\sin(4h),
\end{aligned}
$$

$$
C=1204\epsilon(h)r_o/A_w,\quad
z=C e^{ih},\quad H=\operatorname{hypot}(J,\sqrt{66C}).
$$

若 \(r_o=0\)，令 \(C=a=b=0\)，不计算色相。同时直接从 \(A_c\) 返回 \(J^2\)。这个带符号响应的编码器可以编码那些解码输出合法、但锥响应分量为负的结果；不要仅仅为了观察其外观就抬升（lift）这样的输出。

### 4.3 使用给定的消色差能量解码

对于 \(q=(H,a,b)\)，令 \(C=\operatorname{hypot}(a,b)\)，并给定 \(E\ge0\)，使用

$$
J=\sqrt E,\qquad A_c=A_w(J/100)^{1/\gamma},
$$

$$
(a_o,b_o)=\frac{A_w}{1204\epsilon(h)}(a,b),
$$

$$
\begin{bmatrix}s_R\\s_G\\s_B\end{bmatrix}
=\frac1{1403}
\begin{bmatrix}460&451&288\\460&-891&-261\\460&-220&-6300\end{bmatrix}
\begin{bmatrix}A_c\\a_o\\b_o\end{bmatrix}.
$$

当 \(C=0\) 时，令 \(a_o=b_o=0\)。然后

$$
\mathcal D(q,E)=\rho^{-1}(s),\qquad x_1=Q^{-1}\mathcal D(q,E).
$$

源码的有效性条件要求坐标与输出均为有限值、\(H\ge0\)、\(E\ge0\)，且 \(\max_i|s_i|<399.998\)。超出响应上限属于无效分支，不能把它裁剪之后当作有效结果接受。Python 模型为了安全求值会对 \(s\) 做裁剪，但随后会单独拒绝该结果。

在规则物理点上，\(E=H^2-66C\)。经过防护之后，**使用其携带的 \(E\)**。当为逆变换而编码一个观测到的 RGB 输出时，要从 \(A_c\) 计算 \(E\)，而不是从 \(H^2-66C\) 计算。此处的普通解码不得悄悄再次施加 H–K 防护。

## 5. 阶段 2：色调与保饱和度的缩放

### 5.1 中性尼特与有效基准点

中性尼特坐标是

$$
\nu(v)=\left(\frac{3.05\rho(\max(v,0)/R_w)}{A_w}\right)^\gamma.
$$

对于五个输入的尼特值 \(v_i\)，依次为 Black、Shadows、Midtones、White、Highlights，计算 \(j_i=\nu(v_i)\)，并按顺序强制

$$
j_i\leftarrow\max(j_i,j_{i-1}+.001),\quad i=1,\ldots,4.
$$

定义色调的黑点偏移 \(\beta_T=j_0\)、跨度 \(s_T=j_4-j_0>0\) 以及 \(u_i=(j_i-\beta_T)/s_T\)。目标坐标为

$$
(y_0,y_1,y_2,y_3,y_4)
=\left(0,\nu(\Lambda_{\mathrm{low}}R_w),\nu(.18R_w),1,\nu(P_w)\right),
\qquad \Lambda_{\mathrm{low}}=0.015507796089266005.
$$

像源码那样精确地令 \(y_0=0,y_3=1\)。解析参考实现使用 \(\Lambda_{\mathrm{low}}=0.015507796089266005\)，在默认参考亮度下把 Shadows 置于 \(3.148\) 尼特。1.23.2 版 DCTL 与随附的旧模型使用 \(0.037153526983\)，即 \(7.542\) 尼特。只有这一基准点不同；请只在用同一常数生成的记录之间缩放或比较色调曲线。

### 5.2 核函数与色调函数

对于宽度 \(w>0\)，定义 \(\operatorname{sigmoid}(x)=1/(1+e^{-x})\) 以及

$$
K(t;l,r,w)=\int_0^t\left[\operatorname{sigmoid}\left(\frac{v-l}{w}\right)
-\operatorname{sigmoid}\left(\frac{v-r}{w}\right)\right]dv.
$$

等价地，令 \(\varphi_w(v)=w\log(1+e^{v/w})\)，

$$
K(t;l,r,w)=\varphi_w(t-l)-\varphi_w(-l)-\varphi_w(t-r)+\varphi_w(-r).
$$

在代码中使用数值稳定的 `log1p`、`expm1` 与 softplus 差分。当 \(r-l<.1w\) 时，源码使用窄区间分支：令 \(d=r-l\)，\(a=.387298334621\)，节点 \(s_j=(l+r)/2+(-a,0,a)_jd\)，权重 \((.277777777778,.444444444444,.277777777778)\)。求值

$$
K(t)\approx d\sum_j\omega_j\left[
\operatorname{sigmoid}\left(\frac{t-s_j}{w}\right)
-\operatorname{sigmoid}\left(\frac{-s_j}{w}\right)\right].
$$

这个数值分支是复现源码的一部分。如果目标是与源码精确一致，就应当反转同一分支，而不是反转一个略有差别的理想积分。

对于 \(w_T=.05\,2^{-\mathrm{Fit}_T}\)，定义

$$
m=\min_{i=0}^3\frac{y_{i+1}-y_i}{u_{i+1}-u_i}>0,\qquad
r_i=\max(0,y_{i+1}-y_i-m(u_{i+1}-u_i)),
$$

$$
f(t)=mt+\sum_{i=0}^3r_i\frac{K(t;u_i,u_{i+1},w_T)}{K(1;u_i,u_{i+1},w_T)},
$$

$$
\boxed{T_H(H_0)=100f\left(\max\left(0,\frac{H_0/100-\beta_T}{s_T}\right)\right).}
$$

在 \(t=1\) 处，把输出固定为 \(100y_4\)。中间目标是软约束，而不是精确插值点。高光端点不是裁剪上限：允许 \(t>1\)，并保留正斜率的线性尾 \(mt\)。

如果 \(\beta_T=0\) 且 \(\max_i|j_i-y_i|<3\times10^{-7}\)，源码采用恒等色调旁路。对于生效的曲线，\(T_H\) 在 \(100\beta_T\) 以上严格递增，并把所有更低的明度映射为零。

### 5.3 完整的阶段 2 变换

对于满足 \(J_0^2=H_0^2-66C_0\ge0\) 的有效输入 \(q_0\)，令 \(H_2=T_H(H_0)\)。正缩放因子 \(k_T\) 求解

$$
J_0^2k_T^2+66C_0k_T-H_2^2=0,
$$

于是

$$
k_T=\frac{2H_2^2}{\operatorname{hypot}(66C_0,2J_0H_2)+66C_0},
\qquad q_2=(H_2,k_Ta_0,k_Tb_0),\qquad J_2=k_TJ_0.
$$

\(J\) 与 \(C\) 都按 \(k_T\) 缩放，从而保持 \(75C/J\) 与色相不变。这里的 \(b_0\) 是输入的对手色坐标，与色调黑点偏移 \(\beta_T\) 不是一回事。

在实现上，源码使用的缩放二次式可避免溢出。对于一般的源 \((H,J,C)\) 与目标明度 \(H_t\)，令

$$
r=H_t/H,\quad s=\max(1,r),\quad
u=(J/H)(r/s),\quad v=(33C/H^2)/s,
$$

$$
k=\frac{r/s}{\operatorname{hypot}(u,v)+v}\,r.
$$

若 \(H\le0\) 或 \(H_t\le0\)，使用零输出的极限。精确恒等/旁路的情形可以直接返回输入。对于没有携带 \(J\) 的独立外观探针，\(H^2<66C\) 时仍保留现有的“无适配”行为。完整路径直接使用由编码器导出的有效 \(J\)，并把它缩放后的值一路带过 Tone；经过舍入的 \(H^2-66C\) 不再控制分类器，也不会错误地拒绝一个有效的编码点。无效编码、黑点裁剪与逆域回退仍保留各自独立的检查。

## 6. 阶段 3：系数曲线、贡献与显式操作

本节中始终有 \((H,z)=(H_2,z_2)\)，即**原始的阶段 3 输入**。任何系数或驱动量都不会根据旋转、集中、增益或偏移之后的颜色重新计算。

### 6.1 色调系数曲线

令 \(H_\star=100y_4\)、\(H_i=100y_i\)，并令

$$
p(v)=6v^5-15v^4+10v^3,\qquad
t=p(\operatorname{clamp}(H/H_\star,0,1)),\qquad
\ell_i=p(H_i/H_\star).
$$

对于宽度为 \(w_f=.05\,2^{-\mathrm{Fit}_f}\) 的族 \(f\)，计算

$$
U_i(H)=\frac{K(t;\ell_i,\ell_{i+1},w_f)}{K(1;\ell_i,\ell_{i+1},w_f)},\qquad i=0,1,2,3.
$$

按顺序施加源码的舍入防护：把每个值钳制到 \([0,1]\)，并且不大于前一个值，得到 \(1\ge U_0\ge U_1\ge U_2\ge U_3\ge0\)。

普通权重与 Adaptance 权重分别为

$$
\boldsymbol\beta_f=(1-U_1,U_1-U_2,U_2-U_3,U_3),
$$

$$
\boldsymbol\beta_A=(U_0-U_1,U_1-U_2,U_2-U_3,U_3).
$$

对于存储的高度 \((c_S,c_M,c_W,c_H)\)，系数是它们与相应权重的点积。这些高度的顺序是 Shadows、Midtones、White、Highlights。Concentration 使用 Hue 族的 Fit 与权重。系数在 Highlights 以上保持其最后的高度；Adaptance 在黑点处淡出为零。

分类器使用下面固定的饱和度中点。它没有色调曲线、没有固定 Fit 的插值，也没有随峰值变化的校准。上面的控制系数仍然是随色调变化的。

### 6.2 驱动量与等价的 3×6 贡献矩阵

对于固定指数 \(p_d=2\)，定义

$$
\boxed{\omega(J,C)=\frac{C^2}{C^2+r_s^2\lvert J\rvert^2},\qquad
v_n(C)=\frac{C^2}{C^2+C_n^2},\qquad r_s=\frac{35}{75},\ C_n=2.}
$$

对于 \(J\neq0\)，\(\omega=\lvert s\rvert^2/(\lvert s\rvert^2+s_0^2)\)，其中 \(s=75C/J\)。在 \(J=0\) 处使用有理表达式，绝不要构造可能为无穷的饱和度比值。\(r_s\lvert J\rvert\) 中的绝对值是解析参考实现的带符号对称形式：分类器按 \(\lvert s\rvert\) 划分，因此位于消色差轴下方的颜色与其正值对应物保持相同的低/高隶属度。1.23.2 版 DCTL 改用 \(\max(J,0)\)，把每个负的消色差颜色都送到 \(d_h\)。在跨实现比较驱动量数值之前，先说明采用的是哪种约定。完整的驱动量为

$$
\boxed{d_\ell=v_n(1-\omega),\qquad d_h=v_n\omega,\qquad
d_a=\frac{a}{\operatorname{hypot}(C,2)},\quad
d_b=\frac{b}{\operatorname{hypot}(C,2)}.}
$$

在 \(C=J=0\) 处，把四个驱动量都定义为零。在 \(C=0,J>0\) 处它们也为零。在 \(J=0,C>0\) 处的极限对是 \((0,v_n)\)。较低/较高权重之和为 \(v_n\)，并在 \(s=35\) 处交叉；共享的可见度因子使二者的隶属度在任意输入下都互补。Tone 的共同正缩放 \((J,C)\mapsto(kJ,kC)\) 使 \(\omega\) 不变，但会改变 \(v_n\)。因此分类对饱和度不变；而完整的驱动量数值对曝光并不不变。

在不构造大平方项的前提下求值：

```text
m = max(C, r_s*J)
u = C/m if m > 0 else 0
v = r_s*J/m if m > 0 else 0
D = u*u + v*v
visibility = (C/hypot(C, 2))^2
d_low  = visibility*v*v/D if D > 0 else 0
d_high = visibility*u*u/D if D > 0 else 0
```

同时计算两个归一化分子，可以避免在 `1-high` 中丢失极小的低权重。对于固定的 \(H\)，物理上有效的彩度域是 \(0\le C\le H^2/66\)。交叉点为

$$
C_{50}(H)=r_s\left[\sqrt{H^2+(33r_s)^2}-33r_s\right]
=\frac{r_sH^2}{\operatorname{hypot}(H,33r_s)+33r_s}.
$$

对于较暗的值，使用有理化形式（配合缩放后的乘积）。示波器上的近中性统计选择器使用 \(C\le C_{50}(H)/4\)；该选择器不参与图像分级。分类器中既不出现峰值尼特，也不出现 Fit。

设 \(L_j(H)\) 为以 \(H\) 为单位的 Lightness 贡献曲线，\(R_j(H)\) 为以档为单位的 Chroma 贡献曲线，\(g_0\) 为以档为单位的全局彩度增益，\(\theta_0(H)\) 为以度为单位的色调 Hue 曲线，\(\theta_\ell,\theta_h\) 为以度为单位的全局低彩度/高彩度 Hue 控件。令 \(\kappa=\pi/180\)，

$$
\begin{bmatrix}H_3\\\theta\\\sigma\end{bmatrix}
=
\begin{bmatrix}
1&0&L_\ell(H)&L_h(H)&L_a(H)&L_b(H)\\
0&\kappa\theta_0(H)&\kappa\theta_\ell&\kappa\theta_h&0&0\\
0&(\ln2)g_0&(\ln2)R_\ell(H)&(\ln2)R_h(H)&(\ln2)R_a(H)&(\ln2)R_b(H)
\end{bmatrix}
\begin{bmatrix}H\\1\\d_\ell\\d_h\\d_a\\d_b\end{bmatrix}.
$$

于是 \(H_3=H+\Delta H\)，且 \(g=e^\sigma>0\)。字面实现会对四个驱动量加偏移量分别求值；这个增广矩阵是等价的表述。`pg_attributes` 返回 \((\Delta H,\theta,\sigma)\)，而不是最终的 \((H,a,b)\)。

**色相角的计算属于贡献数学；色相旋转的应用是另一个独立操作。** Hue 行中没有 \(d_a,d_b\) 项。因此 \(\theta\) 依赖于 \(H,C\)，但不独立依赖于输入色相。正是这一性质使得逆变换中可以消去色相。

### 6.3 集中（1.23.2 DCTL 控制）

6.3 与 6.4 节描述的是 1.23.2 版生产阶段，DCTL 与 Blender 发行版实现的就是它。解析参考实现用 6.5 节的色调网与中性目标 Adaptance 取代了这两者，因此第 10–18 节的逆变换构造适用于 1.23.2 的控制集合。请把这两套方案读作共享上方驱动量与系数机制的两个独立阶段，而绝不要读作同一阶段的两套可选参数。

令两条 Concentration 曲线组成 \(v(H)=v_a(H)+iv_b(H)\)，并令

$$
\tau=|v|/.6,\qquad
w_c(H,C)=\frac{\tanh\tau}{\tau}\,v(H)\frac{C^2}{C^2+4}.
$$

在零点处使用 \(\tanh\tau/\tau=1\)。DCTL 对 \(\tau<.001\) 使用 \(1-\tau^2/3+2\tau^4/15\)；Python 模型使用连续的双曲正切表达式。当 \(C>0\) 且 \(u=z/C\) 时，

$$
u_f=\frac{u+w_c}{1+\overline{w_c}u},\qquad z_f=Cu_f.
$$

由于 \(|w_c|<.6<1\)，单位圆上的分母不可能为零。该映射保持 \(C\) 与定向。当 \(C=0\) 时，令 \(z_f=0\)；Concentration 控件为零时使用精确恒等的快速路径。

### 6.4 增益、色相旋转与 Adaptance

对于 Adaptance 强度 \(\alpha\in[0,1]\)，定义

$$
r_A(C)=.25+\frac{.75}{1+(C/30)^2},\qquad
\eta_A(H,C)=\frac{\max(H,0)}{100}
\frac{\alpha r_A(C)}{1-\alpha+\alpha r_A(C)},
$$

$$
B_A(H,C)=\eta_A(H,C)[A_a(H)+iA_b(H)].
$$

原始阶段 3 输出为

$$
\boxed{S(H,z)=\left(H+\Delta H(H,z),\ B_A(H,C)+e^{\sigma(H,z)+i\theta(H,C)}z_f\right).}
$$

等价地，实际的 Hue 操作是对 \((a_f,b_f)\) 施加 \(R_\theta\)，乘以标量 \(g\)，再加上 Adaptance 偏移。源码在 \(H=0\) 时以及阶段 3 未激活时原样返回输入。

### 6.5 参考阶段：色调网、选择性 Adaptance、最终缩放

当前参考用以下内容替代 6.3 和 6.4 节。冻结 Tone 后彩度 \(C_0\)、带符号能量 \(E_0=J_A|J_A|\)、驱动量 \(\mathbf d\) 与非负影调选择器

$$
h=\sqrt{|E_0|+66C_0}.
$$

系数行、网几何与 Adaptance 读取该冻结选择器；在 \(E_0<0\) 时它不同于带符号 \(H\)。像素的彩度、色相和能量仍随操作改变。最终 Scale 单独从 Adaptance 之前的网结果取得。

**直接行。** 对在冻结选择器处求值的明度、彩度系数向量 \(\mathbf L(h)\)、\(\mathbf R(h)\)，以及全局彩度增益 \(g_0\)，

$$
H_1=H+\mathbf L(h)\cdot\mathbf d,\qquad
(a_1,b_1)=2^{g_0+\mathbf R(h)\cdot\mathbf d}(a,b).
$$

实现直接携带对应的带符号能量，不以两个近等平方量相减来重建它。

**网径向场。** 对源半径 \(R\)、目标 \(T\) 和正趾宽 \(\tau\)，

$$
A(C)=\left(1+(C/\tau)^4\right)^{-1/4},\quad
g_{\mathrm c}=\frac{T/R-A(R)}{1-A(R)},\quad
F(C)=C\left[g_{\mathrm c}+(1-g_{\mathrm c})A(C)\right].
$$

其导数为 \(g_{\mathrm c}+(1-g_{\mathrm c})(1+(C/\tau)^4)^{-5/4}>0\)。通过因式分解计算 \(1-A\) 以保留四阶趾部。角向、彩度和 Scale 趾宽是未归一化的软最小值：

$$
\tau_\theta=\left(2^{-8}+\sum_i(0.1R_i)^{-8}\right)^{-1/8},\quad
\tau_C=\left(2^{-8}+\sum_i[(0.1R_i)^{-8}+(0.1T_i)^{-8}]\right)^{-1/8},
$$
$$
\tau_S=\left(2^{-8}+\sum_i[(0.1T_i)^{-8}+(0.1V_i)^{-8}]\right)^{-1/8},
\qquad V_i=2^{\mathrm{log\_scale}_i}T_i.
$$

每个趾宽都不大于 2 或任一参与半径的十分之一。第二个径向场把 \(T_i\) 映到 \(V_i\)。在 Adaptance 前的网彩度 \(C_1\) 处求值，得到 \(\lambda=F_S(C_1)/C_1\)，中性极限为 \(\lambda=1\)。Adaptance 与修复之后不会重新采样该场。

**网角向场。** 令源扇区宽度为 \(w\)、目标端点为 \(\varphi_0,\varphi_1\)、斜率为 \(s=(\varphi_1-\varphi_0)/w\)，共享顶点导数为 \(d=(\tfrac12(s_{\mathrm{left}}^{-4}+s_{\mathrm{right}}^{-4}))^{-1/4}\)。五次 Bézier 纵坐标为

$$
[\varphi_0,\ \varphi_0+wd_0/5,\ \varphi_0+2wd_0/5,\ \varphi_1-2wd_1/5,\ \varphi_1-wd_1/5,\ \varphi_1].
$$

对像素色相 \(\theta\)，施加 \(\theta+S_5(\min(C/\tau_\theta,1))(\mathrm{warp}(\theta)-\theta)\)。正径向系数在目标色相之间按对数插值。影调行在锚点间距上使用五次 smoother 插值，并保持常数尾部；目标色相必须维持严格循环顺序。

**选择性 Adaptance。** 四个中性 a/b 目标用于标定正响应增益。在锚点 \(H_i\) 处，令 \(A_0=A_w(H_i/100)^{1/\gamma}\)、\(r_0=A_0/3.05\)，解码目标响应 \(r_i^*\in(0,400)\)：

$$
m_i=\frac{r_i^*(400-r_0)}{r_0(400-r_i^*)},\qquad g_i=m_i^{1/0.42}.
$$

以基数权重插值 \(\log m_i\)。独立设置 \(R_{1/2}\in[0.05,1]\) 的默认值为 0.25，表示源 \(C/|J_A|\) 在何处达到半影响。冻结掩模为

$$
v=\frac{R_{1/2}^4E_0^2}{R_{1/2}^4E_0^2+C_0^4}.
$$

中性色有 \(v=1\)，彩色且 \(E_0=0\) 时有 \(v=0\)；精确黑保持不变。按 \(r_i'=k^vT_{m_i^v}(r_i)\) 变换响应，其中

$$
T_m(r)=\frac{mr}{1+(m-1)|r|/400}\qquad(|r|\le400).
$$

外部延拓是代数坐标；达到或越过物理极点的响应不直接执行锥响应解压缩。响应由携带能量与对手色坐标重建。公共 \(k\) 以同一冻结影调选择器上的假想中性标定，在 Adaptance 输出处保持其中性的 \(J_A\)；后续 H–K 修复仍可能改变它。

**先修复，再 Scale。** 对 Adaptance 结果执行第 7 节的 H–K 保护，参考能量为 \(E_r=\max(E_0,0)\)。请求 \(H\ge0\) 时输出 \(E_g\ge0\)；\(H>0\) 且 \(E_r>0\) 时有 \(E_g>0\)。负请求 H 保留带符号旁路。随后应用先前选定的 \(\lambda>0\)：

$$
(a,b,E)=(\lambda a_g,\lambda b_g,\lambda^2E_g).
$$

紧凑面板坐标 \((a,b)/\sqrt{C^2+|E|}\) 在该 Scale 下不变。在修复后的非负分支上，\(H(\lambda)=\sqrt{\lambda^2E_g+66\lambda C_g}\) 对每个非黑点严格增加。保护不是幂等操作：导出时再次应用会重新引入随 Scale 改变的饱和度移动。

完整顺序为 **直接行 → 网色相／彩度 → 选择性 Adaptance → H–K 修复 → 公共正值 Scale**。RGB 导出随后仅执行立方体包含。外观 Stack 衔接保留修复与 Scale。完整参考逆由第 20 节经正向验证的搜索给出；第 10–13 节的历史二元逆不实现这一阶段 3。

## 7. H–K 守护：完整前向数学

以下方程定义两种配置共用的独立有界保护。对当前参考，\(q_3\) 是 Adaptance 后、Scale 前的请求，\(E_r=\max(E_0,0)\) 来自携带的 Tone 后带符号能量。历史实现从阶段 2 坐标形成参考能量：\(E_r=\max(H_2^2-66C_2,0)\)；在精确的正外观分支上它等于 \(J_2^2\)，但有限精度的相减不一定等于随行的能量。当前参考改用冻结的随行 \(E_0\)。其历史保护请求为 \(q_3=S(q_2)\)。常量为

$$
k_{\mathrm{HK}}=66,\quad \text{knee}=1,\quad
\text{maximum fractional H lift}=.20,\quad
\lambda=(1+.20)^2-1=.44.
$$

对于 \(H_3\ge0\) 的有限请求，定义

$$
X=H_3^2,\quad C_3=|z_3|,\quad D=X-66C_3,\quad
E_r=\max(E_0,0),
$$

$$
\delta=\frac{E_rX}{E_r+X}.
$$

当分母为零时取 \(\delta=0\)。在求值调和表达式时避免那个可能溢出的乘积：

$$
\delta=\frac{\min(E_r,X)}{1+\min(E_r,X)/\max(E_r,X)}
$$

前提是最大值大于零。

修复后的无彩能量为

$$
E=
\begin{cases}
D,&D\ge\delta,\\
\displaystyle\frac{\delta}{(1+4t+10t^2)^{1/4}},\quad t=(\delta-D)/\delta,
&D<\delta,\ \delta>0,\\
0,&D<\delta,\ \delta=0.
\end{cases}
$$

源用下列形式稳定地求值当前分支：

$$
v=\frac{\delta}{\delta+\max(\delta-D,0)},\qquad u=1-v,
\qquad
E=\frac{\delta\sqrt v}{\sqrt{\sqrt{v^2+4vu+10u^2}}}.
$$

将这份能量修复量分配在明度提升与色度削减之间：

$$
Z=\max(E-D,0),\quad L=\lambda X,\quad
G=\frac{LZ}{\operatorname{hypot}(2L,Z)},
$$

$$
H_g=\sqrt{X+G},\qquad
C_g=\min\left(C_3,\max\left(0,\frac{X+G-E}{66}\right)\right),
$$

$$
z_g=(C_g/C_3)z_3.
$$

分母为零时采用显式的零极限；在 \(C_3=0\) 处保持其零对不变。若 \(E\le D\)，则原样返回 \(q_3\)。在色度非零处，守护保持色相不变。它把 \(E\) 单独携带进 \(\mathcal D(q_g,E)\)。

在正则域 \(E_r>0,H_3>0,C_3\ge0\) 上，活动分支的裁剪算子不会破坏信息：\(0<E<\delta<X\)、\(0\le G<\min(Z/2,L)\)，并且

$$
C_g=C_3-(Z-G)/66>0\quad\text{when active}.
$$

因此在该域上，`min` 与 `max` 只是保护数值边界。此外

$$
H_3\le H_g<1.2H_3,\qquad E+66C_g=H_g^2.
$$

历史执行配置把负请求 \(H_3\)、非有限请求及无效解码导向其回退路径。当前参考修复旁路负 H、拒绝非有限请求，并由立方体导出判断 RGB 合法性。负 \(H_3\) 的平方为正，并不使它满足正分支证明的前提。

当前带符号参考不通过近等的 \(H^2\) 与 \(66C\) 相减来求保护所用的传统亏损。给定权威请求能量 \(E_s\)，令

$$
b=\sqrt{66C},\qquad u=\frac{E_s}{\operatorname{hypot}(\sqrt{|E_s|},b)+b},\qquad
D=\begin{cases}E_s,&E_s\ge0,\\ E_s+2u^2,&E_s<0.\end{cases}
$$

分母为零时采用零极限。在带符号 H–K 映射下，该值等于 \(H^2-66C\)。当前保护旁路负的请求 H；非负 H 修复产生非负携带能量，包含零参考情形。上文的旧回退规则属于历史执行配置。当前参考只在 Scale 前应用一次修复，并把 \(\lambda^2E_g\) 携带到导出。

## 8. 守护是否可逆？定义域与证明

### 8.1 正参考能量：可逆，且只有一个标量根

固定 \(E_r>0\)。给定守卫输出 \((H_g,z_g)\) 且 \(E>0\)，定义

$$
C_g=|z_g|,\qquad U=E+66C_g=H_g^2.
$$

优先用携带来的或直接编码的 \(E\) 与 \(C_g\) 构造 \(U\)。若外部提供的冗余字段超出容差地彼此不一致，应拒绝这条不一致的记录，而不是悄悄改动颜色。

若

$$
E\ge\delta(E_r,U)=\frac{E_rU}{E_r+U},
$$

则唯一的逆请求就是输出本身：守护处于未激活状态。

否则守护处于激活状态，必然有 \(E<E_r\)。对某个试探值 \(X\)，定义

$$
\delta(X)=\frac{E_rX}{E_r+X},\qquad
t(X)=\frac{\sqrt{10[\delta(X)/E]^4-6}-2}{10},
$$

$$
D(X)=\delta(X)[1-t(X)],\qquad
Z(X)=E-D(X),\qquad L(X)=\lambda X.
$$

\(t\) 的公式是下式的非负根

$$
[\delta/E]^4=1+4t+10t^2.
$$

在保证的包围区间上求解

$$
\boxed{F_E(X)=X+\frac{\lambda X\,Z(X)}{\sqrt{4\lambda^2X^2+Z(X)^2}}=U}
$$

$$
\boxed{\max\left(\frac{U}{1+\lambda},\frac{EE_r}{E_r-E}\right)\le X\le U.}
$$

回代得到

$$
\boxed{H_3=\sqrt X,\qquad C_3=\frac{X-E+Z(X)}{66},\qquad
z_3=\frac{C_3}{C_g}z_g.}
$$

在这个激活的正能量分支中，\(C_g>0\) 自动成立。对于 \(C_g=0,E>0\) 的中性输出，应走未激活分支。

### 8.2 标量根为何唯一

在观测到的 \(E\) 固定时，对反转后的能量律求导得

$$
\frac{dD}{d\delta}=-\frac{15t^2}{1+5t}\le0,\qquad
\frac{d\delta}{dX}=\frac{E_r^2}{(E_r+X)^2}>0.
$$

因此

$$
Z'(X)=\frac{15t^2}{1+5t}\frac{E_r^2}{(E_r+X)^2}\ge0.
$$

对于 \(G(L,Z)=LZ/\sqrt{4L^2+Z^2}\)，

$$
\frac{\partial G}{\partial L}=\frac{Z^3}{(4L^2+Z^2)^{3/2}}\ge0,\qquad
\frac{\partial G}{\partial Z}=\frac{4L^3}{(4L^2+Z^2)^{3/2}}\ge0.
$$

于是

$$
\boxed{F_E'(X)=1+\lambda G_L+G_ZZ'(X)\ge1.}
$$

残差严格递增。在包围区间下端点上它非正，而在 \(X=U\) 处对激活的修复取正值。因此恰有一个根。宜用二分法或带保护的 Brent/Newton；就固定参考的守护本身而言，不需要任何多维搜索。

未激活与激活的像不可能重叠：激活结果满足 \(E<\delta(E_r,X)\le\delta(E_r,U)\)，而未激活结果满足相反的不等式。这也证明了 8.1 节中的分支判定。

对每个固定的 \(E_r>0\)，守护将 \(H_3>0,C_3\ge0\) 双射地映到 \(H_g>0,0\le C_g<H_g^2/66\)，并保持色相。在笛卡尔坐标中，中性情形只有一个零对，而不是多个对应不同任意色相标签的不同颜色。

### 8.3 局部条件数与拐点

在 \(X\) 固定、且处于激活分支时，令 \(P_t=1+4t+10t^2\)，

$$
\frac{\partial E}{\partial D}=\frac{1+5t}{P_t^{5/4}}>0.
$$

在强压缩下这个导数会变得很小，因此逆变换可能放大实测 \(E\) 中的误差。数学上的可逆并不意味着经过 float32 舍入或 LUT 插值之后仍有良好的条件数。

\((X,D)\mapsto(U,E)\) 的 Jacobian 行列式为

$$
\det\frac{\partial(U,E)}{\partial(X,D)}
=F_E'(X)\frac{\partial E}{\partial D}>0.
$$

两支在源所意图的 \(C^2\) 拐点处相接。它们在各自的开分支内解析，但不应把整个分段守护描述为跨越每条边界的一个全局解析公式。

### 8.4 退化定义域

| 情形 | 后果与实现策略 |
| --- | --- |
| \(E_r>0,H_3>0\) | 如上所述存在唯一的固定参考逆 |
| \(H_3=0\) | 该平面上任何有限的彩色请求都会被修复为黑；原始色度不可恢复 |
| \(E_r=0,D>0\) | 守护未激活；正能量输出具有恒等原像 |
| \(E_r=0,D\le0\) | 输出落在 \(E=0\) 上；多个原始请求可产生同一输出 |
| 未知 \(E_r\) | 仅凭输出无法确定原始请求；在联合求解中从候选 stage-2 颜色取得 \(E_r\) |
| 无效请求或解码 | 遵循源的回退契约，而不是虚构的正则守护逆 |

对于显式的零参考碰撞，取 \(U=10000\)，选择 \(X=.9U\)、\(G=U-X\)、\(L=.44X\)，并令

$$
Z=\frac{2LG}{\sqrt{L^2-G^2}}.
$$

当 \(E_r=0\) 时，两个请求 \((\sqrt U,U/66,0)\) 与 \((\sqrt X,(X+Z)/66,0)\) 都映射到 \((100,10000/66,0)\)。数值上这两个请求约为 \((100,151.515151515152,0)\) 与 \((94.8683298050514,167.681674763361,0)\)。

对于锥体非负的普通非黑提升输入，外观编码给出 \(J_0>0\)；因此未塌缩的色调结果具有 \(E_r>0\)。零参考退化情形不是常规工作域，但绝不能悄悄宣称它可逆。

## 9. 含符号输入与回退的完整前向执行

### 9.1 正则无提升分支

定义带守护的 stage-3 映射

$$
\widetilde S(q_2)=\mathcal R_{E_r(q_2)}(S(q_2)),\qquad E_r(q_2)=J_2^2.
$$

守护还会返回它所携带的能量 \(E\)。在精确的正则算术下，

$$
F(x)=Q^{-1}\mathcal D\bigl(\widetilde S(T(\mathcal E(QM_1x))),E\bigr).
$$

把 \(\Phi^{-1}\) 记作使用一致能量的普通解码，便得到紧凑表达式

$$
F=\Phi^{-1}\circ\widetilde S\circ T\circ\Phi\circ M_1.
$$

该表达式假定所走的是有效、无提升、完整 grade、且能到达守护/解码路径的分支。精确的未变坐标旁路会跳过该路径，必须由下文完整的源逻辑处理。

### 9.2 舍入保护与白偏移扩展

令 \(v=Px_1\) 为 XYZ，\(c_w=AW_d\)。在非线性阶段之前，源计算

$$
n=Av/c_w,\qquad
\varepsilon_n=4\times10^{-7}|A|\,|v|/c_w,
$$

然后在 \(|n_i|\le(\varepsilon_n)_i\) 处置 \(n_i=0\)。这是依赖相消的置零，而非固定的黑阈值。白色锥体三元组 \(c_w\) 不同于复数形式的 Concentration 参数 \(w_c(H,C)\)。

令

$$
\ell_{\mathrm{lift}}=\max(0,-\min_i n_i),\qquad
n_+=n+\ell_{\mathrm{lift}}\mathbf1,
\qquad w_{\mathrm{RGB}}=P^{-1}W_d=Q^{-1}\mathbf1.
$$

源还会把满足下式的提升分量置零

$$
|(n_+)_i|\le4\times10^{-7}(|n_i|+\ell_{\mathrm{lift}}).
$$

在普通的归一化工作空间中 \(w_{\mathrm{RGB}}=(1,1,1)^T\)，但在不一致的空间里应使用所配置的矩阵，而不要依赖这一捷径。

为了给出忽略这些极小置零区间的数学描述，把 \(\mathcal C_k(n)\) 定义为第 \(k\) 层的归一化锥体核心：编码、施加 Tone、可选地施加 Color、守护并解码。第 2 层包含 Color；第 1 层省略它。于是取最高的有效公共层，

$$
y=Q^{-1}\left[\mathcal C_k(n_+)-\mathcal C_k(\ell_{\mathrm{lift}}\mathbf1)\right]
$$

Blender 合成器的未变核心捷径必须返回提升后的锥体 \(n_+\)，然后恰好减去一次中性核心；1.12.0 版修正了这一捷径。然而，**精确的 DCTL 核心还会接收原始 XYZ 值以保留恒等旁路**，因此其实现契约用下面这段工作 RGB 空间的伪代码来表述更为准确：

```text
Core(v_rgb, n_processed, level):
    q0, J0 = EncodeCones(n_processed)
    if encoding invalid: return INVALID
    q2, J2 = Tone(q0, J0)
    q_requested = Color(q2, J2) if level == 2 else q2
    if q_requested.Hab == q0.Hab exactly:
        return VALID(v_rgb)             # preserve the original value
    qg, E = Guard(q_requested, reference=q2)
    n_out = DecodeCones(qg, E)
    if decode invalid: return INVALID
    return VALID(Q_inverse * n_out)

Forward(x):
    x1 = M1 * x
    if nonlinear reset: return x1
    n = normalized_cones_with_source_zeroing(x1)
    lift = max(0, -min(n))
    n_plus = lifted_cones_with_source_zeroing(n, lift)
    offset_rgb = lift * working_white_rgb
    for level in [2, 1]:
        main = Core(x1 + offset_rgb, n_plus, level)
        if main invalid: continue
        if lift == 0: return main.rgb
        offset = Core(offset_rgb, lift * [1,1,1], level)
        if offset invalid: continue
        result = main.rgb - offset.rgb
        if result finite: return result
    return x1
```

两项使用**同一**层。第 0 层原样返回 stage-1 结果。对正则的有效色调结果，核心第 1 层的守护处于未激活状态，因为其请求等于其参考。完全未激活的 Tone/Color 配置是一个精确的非线性恒等变换。

Python 模型的应用辅助函数通过 stage-2 回退与归一化锥体核心表达同一设计；在每种相消情形下，其恒等/置零算术并不与 DCTL 逐字节相同。做最终一致性测试时，请使用所选渲染器的精确快速路径。任何实值逆都无法恢复被有限精度置零有意抹去的信息。

## 10. 正则分支上的完整非线性逆

### 10.1 编码观测到的输出

对于无提升候选，计算

$$
(q_g,J_g)=\mathcal E(Qy),\qquad E=J_g^2.
$$

使用普通的带符号响应外观编码器。不要对 \(y\) 施加输入侧提升，不要裁剪负的 RGB，也不要再次施加守护。解码后的正则输出可能含有负的 RGB 或锥体分量，但它仍可以是一个有效的外观点。

若编码无效，这并不能排除符号扩展或回退原像，只能排除这一正则完整核心的解释。

### 10.2 优先采用的两个未知量

以 \(J_2>0\) 与 \(C_2>0\) 作为两个未知量，而不是分别独立相减来取得参考能量。对每个试探对，

$$
H_2=\operatorname{hypot}(J_2,\sqrt{66C_2}),\qquad E_r=J_2^2.
$$

这会自动把问题约束在外观定义域之内。优化器可以使用 \(p=\log J_2\)、\(c=\log C_2\)；精确的中性情形 \(C_2=0\) 另行处理。

用这个候选参考撤销守护：

$$
(H_3^*,z_3^*)=\mathcal R_{J_2^2}^{-1}(q_g;E).
$$

星号表示针对当前候选重建出的原始目标，而不是额外的 grade。它随 \(J_2\) 变化而变化。绝不要用中性参考、输出自身的能量，或某个固定的白能量来预先算出一个守护逆。

### 10.3 解析地消去原始色相

计算原始输入项 \(B_A(H_2,C_2)\)、\(\theta(H_2,C_2)\) 与 \(w_c(H_2,C_2)\)。令

$$
V=z_3^*-B_A(H_2,C_2),\qquad R=|V|,
$$

$$
\eta=e^{-i\theta(H_2,C_2)}\frac{V}{R},\qquad
\boxed{u=\frac{\eta-w_c}{1-\overline{w_c}\eta}.}
$$

对于 \(C_2>0\) 的真实原像，\(R=e^\sigma C_2>0\) 且 \(|u|=1\)。若试探的 \(R=0\)，它不可能是增益有限的正色度精确原像。应拒绝或惩罚该试探；数值对数下限不能把它变成一个被接受的根。

构造

$$
q_2=(H_2,C_2\operatorname{Re}u,C_2\operatorname{Im}u).
$$

在这个重建后的**入射**点重新计算源的各驱动量，直接把候选 \(J_2\) 传入，得到 \(\Delta H(q_2),\sigma(q_2)\)。精确求解两个实方程：

$$
\boxed{
\begin{aligned}
H_2+\Delta H(q_2)-H_3^*(J_2^2)&=0,\\
\log(R/C_2)-\sigma(q_2)&=0.
\end{aligned}}
$$

这纳入了 Concentration、Hue、所有 Lightness 与 Chroma 贡献、Adaptance，以及依赖参考的守护。固定参考的守护只贡献一个唯一的内层标量求解，而不是又一个有歧义的逆分支。

第一个残差使用缩放形式，例如除以 \(\max(100,H_g)\)。第二个本身已是对数增益残差。这种缩放是优化器的选择，并不改变精确根。使用信赖域方法或带保护的 Newton，必要时使用多个初值，并利用相邻 LUT 样本的连续性。单个收敛的局部求解并不能证明已找到全部根。

若要实现基于导数的版本，守护的隐式方程 \(F_E(X;E_r)-U=0\) 给出

$$
\frac{\partial X}{\partial E_r}
=-\frac{\partial F_E/\partial E_r}{\partial F_E/\partial X}.
$$

在激活的固定 \(E\) 曲线上，分母至少为 1。应对该隐式解求微分，而不要假定某个带分支的二分程序的结果导数为零。在目标 \(E,U\) 固定时，未激活分支有 \(X=U\)，且关于 \(E_r\) 的导数为零。在对数参数化下，

$$
\frac{\partial H_2}{\partial p}=J_2^2/H_2,\quad
\frac{\partial H_2}{\partial c}=33C_2/H_2,\quad
\frac{\partial E_r}{\partial p}=2E_r,\quad
\frac{\partial C_2}{\partial c}=C_2.
$$

对于新分类器的 Jacobian，使用对数求解坐标 \(\xi=\log J_2\) 与 \(\chi=\log C_2\)（它们就是上面的 \(p,c\) 坐标；二者都不是固定驱动指数 \(p_d\)）。令 \(W=2\omega(1-\omega)\)、\(N=2v_n(1-v_n)\)，则

$$
\begin{array}{c|cc}
 &\partial_\xi&\partial_\chi\\\hline
\omega&-W&W\\
v_n&0&N\\
d_\ell&v_nW&N(1-\omega)-v_nW\\
d_h&-v_nW&N\omega+v_nW
\end{array}
$$

其余系数导数经由 \(H_2(J_2,C_2)\) 按链式法则得到。例如，\(\partial_\xi L(H_2)=L'(H_2)J_2^2/H_2\)，\(\partial_\chi L(H_2)=L'(H_2)33C_2/H_2\)。色相仍然没有独立的输入方向驱动量，因此解析的色相消去依然成立。对复数对公式做实值微分即可；不要假定它们是优化器变量的全纯函数。

### 10.4 逆向 stage 2

给定恢复出的正则 \(q_2,J_2\)，先恢复 \(H_0=T_H^{-1}(H_2)\)。若 Tone 未激活，则 \(H_0=H_2\)。否则求解唯一的标量方程

$$
f(t)=H_2/100,\qquad 0\le t\le\frac{H_2}{100m},\qquad
H_0=100(\beta_T+s_Tt).
$$

该包围区间由 \(t\ge0\) 时 \(f(t)\ge mt\) 得出。在恰好被钉住的端点处，沿用同一钉住规则。源曲线一般无法通过初等函数求逆；由该根或一张经验证的单调逆表来计算 \(T_H^{-1}\)。

逆向的保饱和缩放求解

$$
J_2^2k_-^2+66C_2k_--H_0^2=0,
$$

于是

$$
\boxed{k_-=\frac{2H_0^2}{\operatorname{hypot}(66C_2,2J_2H_0)+66C_2}.}
$$

需要时使用 5.3 节中的缩放二次式求值。随后

$$
q_0=(H_0,k_-a_2,k_-b_2),\quad J_0=k_-J_2,\quad
x_1=Q^{-1}\mathcal D(q_0,J_0^2).
$$

直接携带 \(J_0\)；不要通过相减来重建它的平方。校验这次解码以及原始输入的锥体定义域。

### 10.5 逆向 stage 1 并给出组合逆

对于非奇异的方向目标基，

$$
M_{\mathrm{CAT}}^{-1}=A^{-1}\operatorname{diag}\left(\frac{AW_s}{AW_d}\right)A,
$$

$$
\boxed{M_1^{-1}=2^{-e}P^{-1}M_{\mathrm{CAT}}^{-1}\mathsf B(\mathsf B')^{-1}P.}
$$

实践中，每个 grade 对实际生效的 \(M_1\) 求一次逆或做一次分解，并检查其条件数。曝光/适应可逆并不保证方向控制可逆：Spread \(=-100\) 可以把某个方向塌缩到白上。奇异矩阵需要一份明确声明的近似原像策略，而不是普通求逆。

对于选定的某个可容许非线性分支 \(b\)，

$$
\boxed{F_b^{-1}(y)=M_1^{-1}\Phi^{-1}
\left[T^{-1}\left(\widetilde S_b^{-1}(\Phi(y))\right)\right].}
$$

这就是所需的非线性逆，随后接 stage-1 矩阵逆。通过上面的内层求解，守护已经包含在 \(\widetilde S_b^{-1}\) 中。当守护未激活时，其原始目标就是 \((H_g,z_g)\)，同一组方程退化为无守护的 stage-3 逆。

### 10.6 中性输入与黑的候选

不要用 \(\log C_2\) 来表示精确的中性输入。在 \(C_2=0\) 时，四个贡献驱动量全部消失，\(H_3=H_2\)，且 \(z_3=B_A(H_2,0)\)。通过检验单参数前向曲线来寻找任何中性原像

$$
H_2\longmapsto\mathcal R_{H_2^2}\bigl(H_2,B_A(H_2,0)\bigr).
$$

对正的目标，其可能的 \(H_2\) 落在 \([H_g/1.2,H_g]\) 内。在这个一维区间上求解/搜索，并校验**所有**目标坐标，而不只是明度。这条曲线未必能为任意目标提供原像。观测到的中性也可能是被 Adaptance 抵消掉的非中性输入所致，因此它不能排除一般的二变量搜索。

在精确的黑处，若 Tone 裁剪了一个非零区间，原始输入就无法唯一恢复。一个实用的默认选择是有效原像 \(x=0\)，并标注为选定的黑原像。其他策略选择需要先验；仅凭黑的输出无法推断出来。

## 11. 符号扩展与回退逆

只有当恢复出的 stage-1 锥体满足实际的无提升/舍入分支、且源确实选择了该层时，无提升解才能作为候选。仅有负的 **RGB** 并不足以说明存在带符号锥体提升；请检查归一化锥体。

忽略明确记录的舍入置零，令 \(m_y=Qy\)。对于候选提升 \(\ell_{\mathrm{lift}}>0\) 与核心层 \(k\in\{2,1\}\)，求解

$$
n_+=\mathcal C_{k,b}^{-1}
\left(m_y+\mathcal C_k(\ell_{\mathrm{lift}}\mathbf1)\right),
$$

并满足约束

$$
n_+\ge0,\qquad \min_i(n_+)_i=0.
$$

回代得到

$$
n=n_+-\ell_{\mathrm{lift}}\mathbf1,\qquad
x=M_1^{-1}Q^{-1}n.
$$

每个完整核心逆都采用正则的二变量流程，其核心目标直接由归一化锥体编码得到。第 1 层的核心逆只需要色调逆与普通外观解码。剩下的提升条件是在每个延续的核心逆分支上的一个标量外层方程。与正参考的守护方程不同，这个提升方程**并未被证明单调**，而且可以有多个分支。

对于配置好的有限输入盒 \(\Omega=[x_{\min},x_{\max}]\)，在舍入置零之前，可由 \(A_1=QM_1\) 得到一个有用的精确线性界：

$$
n_{j,\min}=\sum_i(A_1)_{ji}
\begin{cases}(x_{\min})_i,&(A_1)_{ji}\ge0,\\(x_{\max})_i,&(A_1)_{ji}<0,
\end{cases}
\qquad
\ell_{\max}=\max(0,-\min_jn_{j,\min}).
$$

在 \([0,\ell_{\max}]\) 上用分支延拓搜索提升值，或对困难的带符号情形直接做完整前向的 RGB 优化。仅靠变号扫描可能漏掉相切根。若没有配置有限的输入定义域，就不要臆造一个有限的全局提升上界。

始终要测试纯线性候选 \(x=M_1^{-1}y\)：它可能是一次重置、一次逐颜色的未变坐标旁路，或一个第 0 层回退原像。这同样覆盖了那些精确的未变分支：它们跳过了一个否则会修改所请求点的守护。对于第 1 层，重建一个只含色调的候选。无论哪种情况，都运行**完整的前向求值器**。若它选择了更高的有效层，则只有在该更高层仍能重现目标时才接受该候选；标注实际被选中的路径，而不是假设的回退路径。

这些方程说明了如何为完整的分段变换生成候选。它们并不承诺穷举所有带符号根、在数值置零下精确恢复，也不承诺给出全局收敛的求解器。一个实用的尽力而为的实现必须保留一条直接进行完整前向残差最小化的路径。

## 12. 数值守护逆算法

使用无量纲未知量 \(x_X=X/U\)。其包围区间始终包含在 \([1/1.44,1]\) 内，从而避免依赖尺度的求根容差。

```text
InverseGuard(qg, E, Er):
    require finite qg, E > 0, Er > 0, Hg > 0
    Cg = hypot(ag, bg)
    U = E + 66 * Cg
    check consistency of Hg*Hg and U within the input tolerance

    if E >= harmonic(Er, U):
        return (sqrt(U), ag, bg), INACTIVE

    # Here E < Er and Cg > 0.
    lo = max(1/1.44, (E/U) / (1 - E/Er))
    hi = 1

    evaluate(xX):
        X = xX * U
        delta = harmonic(Er, X)
        r = delta / E                  # >= 1 in the exact bracket
        clamp r to 1 only for tolerance-sized bracket roundoff
        t = inverse_energy_parameter(r)
        Z = E - delta + delta*t
        allow only tolerance-sized negative roundoff in Z; then max(Z, 0)
        L = 0.44 * X
        G = L * (Z / hypot(2*L, Z))
        return xX + G/U - 1, X, Z

    solve increasing residual on [lo, hi] by bracketed Brent/bisection
    _, X, Z = evaluate(root)
    H3 = sqrt(X)
    C3 = (X - E + Z) / 66
    return (H3, ag*C3/Cg, bg*C3/Cg), ACTIVE
```

对于 \(r=\delta/E\ge1\)，要避免下式中的相消

$$
t=(\sqrt{10r^4-6}-2)/10.
$$

在 \(r=1\) 附近，有理化后的表达式为

$$
a=\operatorname{expm1}(4\log r),\qquad
t=\frac{a}{\sqrt{4+10a}+2}.
$$

对于较大的 \(r\)，使用

$$
t=\frac{r^2\sqrt{10-6/r^4}-2}{10}
$$

同时监控溢出。若 \(r^2\) 或恢复出的色度超出配置的数值/定义域限制，应报告为病态或超出定义域的候选；不要悄悄把它饱和掉再标成精确逆。在拐点附近 \(Z\) 是三阶小量，因此相减得到的极小负值可以在声明的算术容差内舍入为零。对返回的请求重新运行前向守护。

对普通测试范围，建议的 float64 初始控制为：无量纲求根容差约 \(10^{-12}\)，外层求解的残差目标约 \(10^{-10}\)。这些只是起始数值设置，并非经过验证的感知容差或 GPU 容差。应让容差可配置，并按目标量级缩放最终的 RGB 接受阈值。

## 13. 候选选择与尽力而为行为

对每个目标 \(y\)，实现应返回一个候选 \(\hat x\)、它的前向误差、被选中的分支/层，以及一个状态。建议的状态为 `REGULAR_ROOT`、`NEUTRAL_ROOT`、`SIGNED_ROOT`、`UNCHANGED_ROOT`、`FALLBACK_ROOT`、`APPROXIMATE`、`UNRESOLVED` 与 `SINGULAR_STAGE1`。

用完整选定配置的前向求值器做最终接受测试，例如

$$
\epsilon_{\mathrm{RGB}}=
\frac{\|F(\hat x)-y\|_\infty}{1+\|y\|_\infty}.
$$

这是一个数值重现度量，而不是感知色差。仅有很小的二方程残差并不足够：外观有效性、无提升/带符号选择、参考修复、未变旁路、回退层，以及输入定义域归属，都必须彼此一致。

多根情形需要一套策略。一种可能的默认做法是，借助下式偏好靠近纯线性逆 \(x_{\mathrm{prior}}=M_1^{-1}y\) 的根

$$
d_{\mathrm{prior}}(x)=\|\operatorname{asinh}(x/s_d)-\operatorname{asinh}(x_{\mathrm{prior}}/s_d)\|_2^2,
$$

其中 \(s_d>0\) 是记录在案的 RGB 尺度（例如在归一化工作 RGB 中取 \(s_d=1\)），再加上与相邻已接受 LUT 样本的连续性。先验权重与连续性权重属于逆设计的选择，并非原始前向源的一部分。

若找不到可接受的精确原像，则在配置的定义域 \(\Omega\) 上最小化指定的完整前向误差，可选地施加先验正则：

$$
\min_{x\in\Omega}
\|W_e(F(x)-y)\|_2^2+\mu\,d_{\mathrm{prior}}(x),\qquad \mu\ge0.
$$

\(W_e\) 是显式选定的误差权重矩阵；单位阵是 RGB 的数值默认值。报告得到的前向残差，并把结果标注为 `APPROXIMATE`。只在精确的二方程流形上搜索，并不能证明已对任意 RGB 误差度量找到最佳近似。

一个源所允许的折叠仍然说明了为何分支策略是必要的。把四个 high-chroma-to-Chroma 高度全设为 \(g_h=-4\) stops，其余 stage-3 控制量全为零。在固定 \(H\) 时，

$$
C'=C\,2^{g_hd_h(H,C)},\qquad
\left.\frac{dC'}{dC}\right|_H
=2^{g_hd_h}\left[1+g_h\ln2\,C\left.\frac{\partial d_h}{\partial C}\right|_H\right].
$$

记 \(B=C^2+r_s^2(H^2-66C)\)。在正则正域上，

$$
\left.\frac{\partial\omega}{\partial C}\right|_H
=\frac{r_s^2 C(2H^2-66C)}{B^2},\qquad
v_n'(C)=\frac{8C}{(C^2+4)^2},\qquad
\left.\frac{\partial d_h}{\partial C}\right|_H
=v_n'\omega+v_n\left.\frac{\partial\omega}{\partial C}\right|_H.
$$

\(C'\) 的导数在分类器中点附近为负。在 \(H=100\) 时，p=2 的中点为 \(C_{50}=40.03013072108037\)。两个不同的有效输入（\(h=0\)，约为 \(C=12.049497670414462\) 与 \(C=40.03013072108041\)）都产生原始输出 \((H,a,b)=(100,10.042137411770025,0)\)。两者的守护均未激活，外观解码也都有效。这取代了旧的 \(C_s\) 碰撞示例；不再使用任何历史驱动值。

由于守护的参考随输入变化，仅凭固定参考的双射并不能证明整个 grade 是单射。未激活守护的 p=2 碰撞已足以否定"对所有允许的 grade 都存在普适唯一逆"这一说法。

## 14. 正向表与标量逆表

### 14.1 解析导数成分

对于普通核，其中 \(s_l=\operatorname{sigmoid}((t-l)/w)\)，\(s_r=\operatorname{sigmoid}((t-r)/w)\)，

$$
K'(t)=s_l-s_r,\qquad
K''(t)=\frac{s_l(1-s_l)-s_r(1-s_r)}{w}.
$$

对于窄区间求积分支，要对实际使用的求积式求导：

$$
K'(t)\approx\frac{r-l}{w}\sum_j\omega_j s_j^*(1-s_j^*),
$$

$$
K''(t)\approx\frac{r-l}{w^2}\sum_j\omega_j s_j^*(1-s_j^*)(1-2s_j^*),
\quad s_j^*=\operatorname{sigmoid}((t-s_j)/w).
$$

在归一化明度区间内，

$$
p'(x)=30x^2(1-x)^2,\qquad p''(x)=60x(1-x)(1-2x).
$$

对于归一化过渡 \(K(p(x))/K(1)\)，其一阶与二阶导数按链式法则给出：

$$
U_i'=K_i'(p)p'/K_i(1),\qquad
U_i''=[K_i''(p)(p')^2+K_i'(p)p'']/K_i(1).
$$

采用相同的权重差与高度点积即可得到曲线导数。这些是相对于归一化 \(x=H/H_\star\) 的导数；若要求对 \(H\) 的导数，则分别除以 \(H_\star\) 或 \(H_\star^2\)。

### 14.2 现有正向表

独立解析参考直接求值 Tone 与阶段 3 系数函数。其加速 `BakeStack` 预备共享标量逆 Tone 表。这是不同的执行配置；加速资源不会重新定义解析模型。

| 配置 | 阶段 2 | 阶段 3 |
| --- | --- | --- |
| 独立解析参考 | 闭式正向 Tone | 闭式系数与修正后的 Warp |
| 参考 `BakeStack` | 预备的逆 Tone 表 | 参考正向内核 |
| 保留的生产逆 | 具体配置的逆 Tone 预备 | 保留的控件和顺序 |
| Next Blender 产品 | 阶段 1／Tone 实现 | 尚未实现 Warp |

参考 `BakeStack` 使用的共享逆 Tone 表会在预备时求解标量逆函数 \(t(H)\)，并以 \(u=\log(1+H/s)\) 为自变量表示 \(q(H)=t(H)/H\)，其中 \(s\) 为表的尺度。它使用自适应节点轴与五次 Hermite 插值，并以解析方式计算正线性尾部。区间会持续细分，直到五个比例探针与针对 \(q>0\) 及 \(Hq\) 递增性的 Bernstein 检查通过。预备受 `MAX_CELLS=2048`、`MAX_ROUNDS=32`、`MAX_ROOT_EVALUATIONS=80` 与 64 KiB 预算限制；上限不是存储尺寸。Next 的实验性 Color 预备不能作为已交付 Warp 的证据。

**历史残差坐标正向表。** 以下构造与均匀 2048 单元示例属于保留的历史推导；它们不描述参考 `BakeStack` 的逆 Tone 表。复现历史实现输出时，应使用该实现自己的表布局。

Tone 以解析方式保留其线性尾部。它只对

$$
\mathcal V(\zeta)=\sum_i r_i\frac{K(t;u_i,u_{i+1},w_T)}{K(1;u_i,u_{i+1},w_T)},
\qquad t=\frac{\zeta}{1-\zeta},\qquad \zeta=\frac{t}{1+t},
$$

制表，并对 \(f(t)=mt+\mathcal V(\zeta)\) 求值。端点 \(\zeta=1\) 使用有限的残差极限，且极限导数为零。源码的表生成用其规定的大 \(t\) 求值来近似该端点。不要把这一构造替换为在 Highlights 处裁剪整条 tone 曲线的表。

对于 \(x_i=i/N\)、\(N=2048\)、步长 \(\Delta=1/N\)，采样标量曲线 \(g\)，并存储 float32 端点三元组

$$
(g_i,\ \Delta g_i',\ \Delta^2g_i'').
$$

令 \(d_i=\Delta g_i'\)、\(c_i=\Delta^2g_i''\)。在区间 \(i\) 内，以局部坐标 \(u=Nx-i\) 构造

$$
a_0=g_i,\quad a_1=d_i,\quad a_2=c_i/2,
$$

$$
\Delta_0=g_{i+1}-a_0-a_1-a_2,\quad
\Delta_1=d_{i+1}-a_1-2a_2,\quad
\Delta_2=c_{i+1}-2a_2,
$$

$$
a_3=10\Delta_0-4\Delta_1+\Delta_2/2,\quad
a_4=-15\Delta_0+7\Delta_1-\Delta_2,\quad
a_5=6\Delta_0-3\Delta_1+\Delta_2/2.
$$

用 Horner 法则求值 \(\sum_{j=0}^5a_ju^j\)。相邻区间使用相同的已存储值、斜率与曲率。

当前逆 Tone 表使用相同的五次 Hermite 插值基，但作用于自适应的 \(u=\log(1+H/s)\) 节点与存储的逆比例 \(q=t/H\)；它不使用上面的历史残差坐标、均匀网格或正向残差表。其单调性门限会在接纳每个区间前检查实际存储的插值。当前没有部署阶段 3 表：四族曲线与 \(512\times70\) 图集的描述属于 14.2 节指出的不可达旧版生成器。p=2 分类器由随行的 \(J_2\) 与当前 \(C_2\) 解析求值；高度点积仍然实时计算。

### 14.3 新的逆向 Tone 表

这里给出的是一种通用标量逆表构造。当前参考 `BakeStack` 使用的是 14.2 节所述的专用实现；本节并非其存储格式或细化方法。

即使不存在初等逆表达式，也可以由求根得到的端点值构造标量逆表。对于 \(g=T_H^{-1}\)，

$$
g'(y)=\frac1{T_H'(g(y))},\qquad
g''(y)=-\frac{T_H''(g(y))}{[T_H'(g(y))]^3}.
$$

选定并记录该表的输出明度域与归一化方式，然后在构造端点 jet 之前把导数换算到该归一化坐标。在表量化之后验证单调性、端点、外插以及正向复现。不要把黑裁剪区间纳入唯一可逆性的断言之中。

**这张一维表可以加速 tone 逆。它无法表示一般性的耦合 stage-3 逆。** Stage 3 连同其依赖输入的 guard，仍然需要耦合求值器或预先烘焙的 3D 逆 LUT。

## 15. 端到端逆向烘焙算法

```text
PrepareGrade(configuration):
    resolve effective working space, white, reference/peak nits, controls
    build the chosen analytic or deployed-table forward evaluator
    build M1 and factor/invert it; record its condition estimate
    prepare tone and coefficient kernels/tables
    retain the complete source forward evaluator for acceptance tests

InverseCandidateRegular(target_rgb, seed):
    target = EncodeCones(Q * target_rgb)           # no new lift or guard
    if invalid or target.E <= 0: return NO_REGULAR_CANDIDATE
    solve for log(J2), log(C2):
        H2 = hypot(J2, sqrt(66*C2))
        raw_target = InverseGuard(target.q, target.E, J2*J2)
        compute BA, theta, concentration parameter from H2,C2
        remove BA and theta; analytically invert concentration direction
        construct q2; evaluate original-input p=2 drivers with candidate J2
        drive lightness and log-gain residuals to zero
    invert scalar tone lightness and reverse its quadratic scaling
    plain-decode q0 carrying J0*J0
    apply M1_inverse
    return candidate plus diagnostic residuals

Inverse(target_rgb):
    handle exact reset, black, and singular-matrix policy
    test the linear-only candidate for unchanged or fallback preimages
    collect regular candidates from appropriate seeds/continuation
    separately test the exact neutral-input curve
    if needed, generate signed-lift and fallback candidates
    run every candidate through the complete source forward evaluator
    reject invalid domain, wrong branch/level, or excessive residual
    select an accepted candidate using the documented prior/continuity policy
    if none accepted, run configured full-forward best-effort optimization
    return input_rgb, status, selected level/branch, forward error
```

烘焙时，在每个**逆向输入**格点上直接针对所选源模型求值这个逆。这样可避免引入中间的正向 3D LUT 及其插值误差。它并不消除最终逆 LUT 自身的插值误差。

至少记录以下内容：

- 工作原色/白点以及所有生效的 grade/观看参数。
- 该逆是否覆盖 stage 1，还是期望 stage 1 被单独施加。
- 正向求值器的 profile、源码版本以及算术/表精度。
- 输入与输出 shaper、带符号值策略以及域边界。
- LUT 的格点尺寸、轴顺序与插值方法。
- 分支选择策略、求解器容差、未解析/近似计数以及验证误差。

对于编码逆之输入 \(y\) 的 LUT shaper \(\mathcal S_{\mathrm{in}}\) 与编码其结果 \(x\) 的输出 shaper \(\mathcal S_{\mathrm{out}}\)，所存储的函数为

$$
L(u)=\mathcal S_{\mathrm{out}}\left(
F_b^{-1}(\mathcal S_{\mathrm{in}}^{-1}(u))\right).
$$

要明确规定实际的 shaper 及其定义域；不要假定 \([0,1]\) 的场景线性 RGB 就能覆盖 HDR 或带符号颜色。既要验证采样节点，也要验证格点外的插值点。先逆后正复现是主要检验；当所选的逆挑选了另一个合法原像时，先正后逆的恢复可以合理地不一致。

## 16. 验证证据与实现验收测试

这项推导由 `tests/blender/test_forward_inverse.py` 针对当前解析模型进行检验。该测试在逆 Hue 计算中使用新的有理驱动式，并把候选 \(J_2\) 直接传入 contribution 求值。这些 float64 局部分支检查并不能确立全局求解器收敛性，也不能确立逆 LUT/GPU 精度。

| 检查 | 结果 |
| --- | --- |
| Guard 逆，2400 次请求；1603 次活跃 | 逐分量归一化恢复误差最大 7.8e-13 |
| 完整逆，48 个 RGB 输入，三个阶段全部活跃；24 个活跃 guard | RGB 恢复绝对误差最大 8.13e-14 |
| 对恢复出的输入做正向复现 | RGB 绝对误差最大 1.25e-13 |
| 零参考能量 guard 碰撞 | 不同请求之间的偏差在 1.42e-14 以内 |

正向实现还由以下内容覆盖：独立的有理驱动式测试、float32/float64 下真实的图表达式算术、编译后的 DCTL 验收/一致性测试、Blender 5.2.2 的 CPU 合成器与 Cycles 渲染、scope/prepared-path 检查，以及被保留并单独评审的 p=2 夹具基线。历史的 `docs/engineering/p2-validation-report.md` 记录了那次分类器集成；当前的采样验证记录在[测试与测量](testing.md)中。本文不声称存在任何 Resolve GPU 结果或已完成的 Buck2 发布门禁。

guard 探针使用的请求 \(H_3\) 大约从 .01 到 1000，参考比 \(E_r/H_3^2\) 从 \(10^{-4}\) 到 \(10^4\)，彩度比 \(66C_3/H_3^2\) 从 \(10^{-3}\) 到 \(10^3\)。它们使用直接随行的输出能量。这些独立的 guard 探针不需要外观域解码。

### 16.1 具体组合夹具

工作空间：Linear Rec.709，D65 目标白。所有未作说明的控件保留其源码默认值。

| 设置 | 取值 |
| --- | --- |
| Exposure | \(.4\) stops |
| 源白 \(xy\) | \((.34,.35)\) |
| 各方向内部 Balance，红/蓝 | \((.12,-.08)\) stops |
| Spread，红/蓝 | \((12,-8)\) percent |
| Heading，红/蓝 | \((7,-9)\) degrees |
| Tone 输入 nits，从 Black 到 Highlights | \((0,10,45,260,1250)\) |
| Reference、peak、Tone Fit | \(203,1000,0\) |
| 全局彩度增益 | \(1.2\) stops |
| 全局低彩度/高彩度 Hue | \((13,-21)\) degrees |
| Adaptance 强度 | \(.63\) |
| Adaptance/Lightness/Chroma/Hue Fit | \((0,1,0,2)\) |

对于下列每个族/驱动式，把它的四个色调高度设为 `base * (0.6, 1.1, 0.85, 1.4)`：

| 源码 stem | Base |
| --- | --- |
| `j_low`、`j_high`、`j_a`、`j_b` | 分别为 \(-3,-8,2,-1\) |
| `c_low`、`c_high`、`c_a`、`c_b` | 分别为 \(.08,.15,.05,-.04\) |
| `adaptance_a`、`adaptance_b` | 分别为 \(1,-1.5\) |
| `hue` | \(7\) |
| `concentration_a`、`concentration_b` | 分别为 \(.12,-.08\) |

一个为显示而取整后的测试向量是：

```text
input RGB:       (1.0, 0.05, 0.03)
q0 = H,a,b:      (92.46258977977801, 39.67856894717561, 28.591165410325175)
q2 = H,a,b:      (84.3346436998987, 35.39010703671729, 25.501030682910294)
raw q3:          (79.33925026602888, 104.53290832077005, 35.128154302716894)
guarded qg:      (85.31759837041311, 88.41997631419794, 29.713423469253726)
reference Er:    4233.368368928621
guard output E:  1122.6757952035593
output RGB:      (0.6159268568211308, -0.11182657798449142, -0.010366096646826079)
recovered RGB:   (0.9999999999999997, 0.05000000000000013, 0.029999999999999954)
```

guard 显著改变了这一请求，且输出包含负 RGB。在求逆之前裁剪该 RGB，会破坏所述的往返。该逆是由输出的编码无彩响应算出观测到的 \(E\) 的，而不是减去 \(H_g^2-66C_g\)。

48 个案例的夹具使用了下面六个显式输入，外加 42 个带种子的随机输入。随机发生器为 NumPy 的 `default_rng(401936)`；2400 个 guard 探针先消耗了它的抽样，顺序为 \(H=10^{\operatorname{uniform}(-2,3)}\)、\(E_r/H^2=10^{\operatorname{uniform}(-4,4)}\)、\(66C/H^2=10^{\operatorname{uniform}(-3,3)}\)，以及 \(h=\operatorname{uniform}(-\pi,\pi)\)。每次抽样都是长度为 2400 的数组。随后在 \([-1.3,.5]\) 上均匀地抽一个 `(42,3)` 数组，并逐分量地把 10 提升到这些值。这些显式输入是：

```text
(1,.05,.03), (.2,.7,.1), (.1,.2,1), (.5,.3,.2), (2,.1,.1), (.3,.3,.3)
```

所有被测的 stage-1 锥体三元组均为正，且全层级解码有效。这些完整逆测试未涉及带符号 lift 或 fallback 逆。它们使用的候选种子由观测到的目标导出，而不是由已知的原始 RGB 导出。第 13 节中的 p=2 碰撞示例是另一项非唯一性检查。

### 16.2 对工程师实现所要求的测试

在使用生产用逆 LUT 之前，请验证：

0. p=2 对及其随行 \(J_A\) 算术、\(d_\ell+d_h=v_n\)、精确的中性/黑行为、\(s=35\) 交叉点、导数公式，以及在正向 Tone 为正比例缩放下的分类器不变性。可见性淡出要单独测试。

1. 精确 reset 以及仅曝光/仅矩阵的 grade；报告奇异或病态矩阵。
2. 纯 Tone、纯 Hue、纯 Concentration、纯 gain、纯 Adaptance，以及带有不同色调高度的混合 grade。
3. guard 拐点两侧、拐点处，以及带随行能量的严重活跃修复。
4. 极小正 \(J_2\)、极小正 \(C_2\)、精确中性输入、黑、高动态范围，以及合法的负 RGB 输出。
5. 零参考能量与零请求明度简并情况，作为显式的非唯一案例。
6. 带符号的归一化锥体 lift 与成对的层级选择，包括合法的 level-1 与 level-0 fallback 候选。
7. 错误层级候选的检测：对源码实际选择的任何更高层级求值，要求其完整输出匹配，并报告实际路径。
8. 源码允许的创意折叠，以及跨相邻 LUT 采样点的确定性分支选择。
9. 实际部署的表/浮点精度、响应极点拒绝，以及相消置零。
10. LUT 节点误差与格点外误差，使用精确的目标 shaper/插值；不得静默裁剪 RGB。

对于已知为单射的局部夹具，要同时检查 \(F^{-1}(F(x))\approx x\) 与 \(F(F^{-1}(y))\approx y\)。对于非唯一的夹具，则要求后者以及文档化的分支策略成立，而不是强求恢复不可观测的原始输入。

## 17. 实现边界

本规范给出完整的数学流水线、针对正则固定参考 H–K guard 的可逆性证明、其组合 stage-3 逆的双变量归约，以及经核验的数值示例。这些验证并不构成生产用逆向 baker、对所有原像的完整枚举、带符号/fallback 收敛性证明，也不构成目标 GPU 认证。

预期的生产路径是：直接对所选的正向模型求值；用归约后的逆与显式的分量逆得到候选；通过完整的源码分支逻辑验证候选；选定一致的分支或记录近似结果；然后烘焙并测试最终的逆 LUT。

## 18. Blender 逆向与 Stack 实现契约

CPU 实现位于 `model/inverse.py`、`model/transforms.py` 和 `model/lut.py`；`graph/lut.py` 与 `graph/stacks.py` 把它与 Blender 集成。它的目标是 **float64 解析 Python 正向模型**，包括其实际的锥体舍入、lifting、bypass 与 fallback 决策。从 1.23.0 起，`model/gpu.py` 与 `model/gpu_shader.py` 提供下文所述的已安装 float32 解析 profile。这两者都不以精确逆转 Direct 的 Quintic 求值器或插值正向 cube 为目标。

### 18.1 已实现的数值逆

`model/analytic.py` 求值的 float64 正向方程与独立的 `color.Model` / `tone.Model` 参考实现相同。它共享相同的系数权重，跳过零项，并且只求值所需的稳定 softplus/fallback 分支。带符号 lift 的中性偏移化简为 \(q_3=(H_2,\alpha H_2 A_a(H_2)/100,\alpha H_2 A_b(H_2)/100)\)：在 \(C=0\) 时，所有 contribution 驱动式都消失，Adaptance 包络为 \(\alpha H_2/100\)。guard/decoder 随后共享其重复的半径与能量计算，同时保留分支决策。它不含任何采样系数表或中间 LUT。该逆是半解析的：显式的分量逆对正则问题作归约，而有界的数值求解选出可用的原像。

#### 带保护的标量逆

对于第 12 节中活跃、正能量、固定参考的 guard 逆，使用观测能量 \(e\)、参考能量 \(e_0\) 以及 \(u=e+66C_g\)。令 \(x=X/u\)，其中 \(X\) 为未知的原始明度平方。求解

$$
f(x)=x+G(xu)/u-1=0,\qquad
\max\!\left(\frac1{1.44},\frac{e/u}{1-e/e_0}\right)\le x\le1.
$$

活跃分支有 \(e<e_0u/(e_0+u)\)，因此其下界的分母为正。在候选 \(X=xu\) 处定义

$$
\delta=\frac{e_0X}{e_0+X},\quad r=\max(1,\delta/e),\quad
 t=\frac{\sqrt{10r^4-6}-2}{10},\quad
Z=\max(0,e-\delta+\delta t),\quad L=.44X,\quad
D=\sqrt{4L^2+Z^2},\quad G=LZ/D.
$$

在 \(r=1\) 附近使用有理化后的表达式 \(t=(r^4-1)/(\sqrt{10r^4-6}+2)\)，与源码一致。对于活跃内部区域，

$$
Z_X=\left(\frac{e_0}{e_0+X}\right)^2
\left(t-1+\frac{2r^2}{\sqrt{10-6/r^4}}\right),
\qquad
f'(x)=1+.44\left(\frac ZD\right)^3
       +\frac12\left(\frac{2L}D\right)^3Z_X.
$$

从 \(x=1\) 开始。更新符号区间，然后若 \(x-f/f'\) 严格落在区间内就用它；否则用区间中点。当 \(|f|<8\times10^{-14}\) 时停止，最多 16 步 Newton。其余行在保留的区间上完成 42 次二分。重构 \(H_3=\sqrt X\)，并把观测到的色度向量乘以 \((X-e+Z)/(66C_g)\)。这改变的是数值方法，而不是固定参考的 guard 方程。非活跃与简并情形保持前文所述的分支行为。

对于 Tone，把归一化重映射写作

$$
R(t)=m t+\sum_i\frac{v_i}{n_i}K_i(t),\qquad
 t=\max(0,(H_0/100-b)/s_b),
$$

其中 \(m>0\) 是存储的基础斜率，\(v_i\ge0\) 是残差高度，\(n_i=K_i(1)\)，\(b\) 是归一化输入黑，\(s_b\) 是归一化源跨度。远离窄区间求积分支时，

$$
R'(t)=m+\sum_i\frac{v_i}{n_i}
\left[\sigma((t-l_i)/w)-\sigma((t-r_i)/w)\right],
\qquad \sigma(z)=\frac1{1+e^{-z}}.
$$

对于 \(r_i-l_i<.1w\)，对正向实现所使用的同一个三节点求积式求导：\(K'_i(t)=(r_i-l_i)\sum_j a_j\sigma_j(1-\sigma_j)/w\)，并使用源码的求积节点/权重。这样保留的是已实现的正向曲线，而不是对另一个近似求导。

在 \([0,(H_2/100)(1+10^{-12})/m]\) 上求解 \(R(t)=H_2/100\)。用已知目标/源地标的线性插值作种子，在最后一个地标之上使用基于斜率的外插。最多使用 24 步带区间的 Newton，当 \(|R(t)-H_2/100|<2\times10^{-14}(1+H_2/100)\) 时停止。未完成的行使用原有的 44 步单调二分兜底。然后施加第 9 节的解析饱和逆。Black 使用显式的零输出约定。

#### 共享池阻尼 Broyden 求解

正则色度候选使用第 10 节的双未知量重构，包括解析的 Hue/Concentration 撤销与标量 guard 逆。坐标为 \(v=(\log J_2,\log C_2)\)，界定在 \([-18,14]^2\)。中性候选与黑候选避免对零彩度取对数。每个得到的 RGB 候选都要通过完整的非线性正向函数 \(N\) 验证，包括 lifting、bypass 与 fallback 选择。

正则双变量系统在初始化与恢复时提供其解析的分段 Jacobian \(D=\partial r/\partial v\)。通用全正向 RGB 系统用单侧坐标扰动 \(h=2\times10^{-5}\) 初始化并恢复 \(D\)。两者使用相同的接受步 Broyden 更新。对每个未解析的行计算

$$
\left[D^TD+\lambda\bigl(1+\operatorname{tr}(D^TD)\bigr)I\right]p=D^Tr.
$$

从 \(\lambda=10^{-7}\) 开始。把 \(\lVert p\rVert_\infty\) 限制在 1.5，并对 \(\alpha\in\{1,1/2,1/8\}\) 尝试 \(v-\alpha p\)，同时遵守坐标边界。接受第一个满足有限性且严格减小 \(\lVert r\rVert_2^2\) 的试探。对于被接受的位移 \(s=v_{new}-v\) 与残差变化 \(z=r_{new}-r\)，更新

$$
D_{new}=D+\frac{(z-Ds)s^T}{s^Ts}.
$$

当 \(s^Ts\le10^{-24}\) 时省略该秩一贡献。被接受的步把阻尼乘以 .2，下限为 \(10^{-12}\)；被拒绝的步把阻尼乘以 10，上限为 \(10^6\)。在拒绝之后以及每 12 次迭代后刷新一次近似 Jacobian。在点未改变时已测得的 Jacobian 会被复用，即使阻尼正在变化。正则系统以解析方式恢复；通用 RGB 系统以有限差分恢复。两者都不会在每个被接受的步上重新测量 Jacobian。

对于双变量系统，在求解阻尼正规方程时要避免相减两个几乎相等的乘积。用下式定义局部 Jacobian 元素与阻尼移位

$$
D=\begin{bmatrix}a&b\\c&d\end{bmatrix},\quad
\delta=ad-bc,\quad \tau=a^2+b^2+c^2+d^2,\quad
\mu=\lambda(1+\tau),\quad \Delta=\delta^2+\mu(\tau+\mu).
$$

对于残差 \((r_0,r_1)^T\)，该步为

$$
p_0=\frac{\delta(dr_0-br_1)+\mu(ar_0+cr_1)}{\Delta},\qquad
p_1=\frac{\delta(ar_1-cr_0)+\mu(br_0+dr_1)}{\Delta}.
$$

这与前述阻尼正规方程相同，只是在秩一情形下使用了免相消的行列式与分子。三变量的 RGB 系统保留通用的矩阵求解。

#### 解析正则 Jacobian

使用 \(J=J_2>0\)、\(C=C_2>0\)、\(v=(\xi,\chi)=(\log J,\log C)\) 以及 \(H=\sqrt{J^2+66C}\)。本小节中所有梯度都是关于 \(v\) 的行向量。于是

$$
\nabla H=\left(\frac{J^2}{H},\frac{33C}{H}\right),\qquad
\nabla E_r=(2J^2,0).
$$

固定观测的 guard 逆返回请求的 \((H_3,a_3,b_3)\)。在活跃的 guard 分支上，其标量方程为 \(X+G(X,Z(X,E_r))=U\)；观测能量 \(e\)、修复能量 \(U\) 与观测色相都是固定的。使用上文 guard 逆小节中的 \(t,r,L\) 各量，并记 \(D_g=\operatorname{hypot}(2L,Z)\) 为其标量分母，以区别于求解器 Jacobian \(D\)。于是

$$
A_Z=t-1+\frac{2r^2}{\sqrt{10-6/r^4}},\quad
Z_X=A_Z\left(\frac{E_r}{E_r+X}\right)^2,\quad
Z_{E_r}=A_Z\left(\frac{X}{E_r+X}\right)^2,
$$

$$
G_X=.44\left(\frac Z{D_g}\right)^3,\qquad
G_Z=\frac12\left(\frac{2L}{D_g}\right)^3,\qquad
X_{E_r}=-\frac{G_ZZ_{E_r}}{1+G_X+G_ZZ_X},\qquad
\frac{dZ}{dE_r}=Z_XX_{E_r}+Z_{E_r}.
$$

因此 \(dH_3/dE_r=X_{E_r}/(2\sqrt X)\)。若观测到的色度向量为 \(z_g=a_g+ib_g\)，其请求的对应量为 \(z_3=z_g(X-e+Z)/(66C_g)\)，所以

$$
\frac{dz_3}{dE_r}=\frac{z_g}{66C_g}
\left(X_{E_r}+\frac{dZ}{dE_r}\right).
$$

在非活跃分支上，关于参考能量的两个导数都为零。把这些标量导数乘以 \(\nabla E_r\)，即可得到它们在求解器坐标下的梯度。这相当于把依赖参考的 guard 与 stage 3 联合求导；它并不冻结未知的 stage-2 能量。

要在每条系数曲线实际被裁剪的 smoother 位置对其求导。对于 \(s=\operatorname{clip}(H/H_{\rm high},0,1)\) 与 \(t=s^3(6s^2-15s+10)\)，

$$
\frac{dt}{dH}=\frac{30s^2(s-1)^2}{H_{\rm high}}.
$$

把已实现的核导数乘以该因子以及核归一化。核的窄区间求积导数就是上文为 Tone 定义的同一个导数。被裁剪的核值在其开区间之外导数为零；累积最小值携带被选中操作数的导数。把得到的基导数乘以存储的系数高度。Fit 相同的族共享其核计算；系数为零的族无需曲线求值。

对于色度重构，定义 \(o\) 为 Adaptance 复偏移，\(z=z_3-o\)，\(R=|z|>0\)，\(\eta=e^{-i\theta}z/R\)，以及 \(w\) 为有界的 Concentration 圆盘参数（含其中性淡出）。解析重构出的输入方向为 \(u=(\eta-w)/(1-\overline w\eta)\)。其梯度为

$$
\nabla\log R=\frac{\operatorname{Re}(\overline z\nabla z)}{R^2},\qquad
\nabla\eta=e^{-i\theta}\frac{\nabla z-z\nabla\log R}{R}
                -i\eta\nabla\theta,
$$

$$
\nabla u=\frac{\nabla\eta-\nabla w
             +u(\eta\nabla\overline w+\overline w\nabla\eta)}
                  {1-\overline w\eta}.
$$

使用第 10 节的分类器梯度对 p=2 的低彩度/高彩度对求导。对于 \(n=C/\operatorname{hypot}(C,2)\)，\(\nabla n=(0,n(1-n^2))\)，因此方向驱动式的梯度为 \(\nabla(n\operatorname{Re}u)\) 与 \(\nabla(n\operatorname{Im}u)\)。若 \(h(H)\) 是标量 Hue 曲线，\(h_\ell,h_h\) 是以度表示的全局低/高 Hue 控件，则

$$
\nabla\theta=\frac\pi{180}\left[h'(H)\nabla H+h_\ell\nabla d_\ell+h_h\nabla d_h\right].
$$

对于有界 Concentration 控件 \(v_c(H)\in\mathbb R^2\)，令 \(t=\lVert v_c\rVert/.6\)、\(f(t)=\tanh(t)/t\)、\(\beta=f(t)v_c\)。其 tone 导数为

$$
\beta'(H)=f(t)v_c'(H)+k(t)v_c\,[v_c\cdot v_c'(H)],\qquad
k(t)=\frac{1-\tanh^2(t)-f(t)}{(.6t)^2}.
$$

在 \(t\) 很小时求值 \(k(t)=[-2/3+8t^2/15-34t^4/105]/.6^2\)，并取连续极限 \(f(0)=1\)。把 \(\beta\) 的两个分量表示为复数并令 \(w=\beta n^2\)；于是

$$
\nabla w=n^2\beta'(H)\nabla H+\beta(0,2n^2(1-n^2)).
$$

对于 Adaptance，使用 \(s=(C/30)^2\)、\(r_A=.25+.75/(1+s)\)、\(b_A=1-\alpha+\alpha r_A\) 以及 \(\omega_A=\alpha r_A/b_A\)，其中 \(\alpha\in[0,1]\) 是固定强度。于是

$$
\partial_\chi r_A=-\frac{1.5s}{(1+s)^2},\qquad
\partial_\chi\omega_A=\frac{\alpha(1-\alpha)\partial_\chi r_A}{b_A^2}.
$$

若 \(a_A(H)\) 是复 Adaptance 曲线，则 \(o=a_AH\omega_A/100\)，所以

$$
\nabla o=\frac{\omega_A}{100}[Ha_A'(H)+a_A(H)]\nabla H
       +\frac{H a_A(H)}{100}(0,\partial_\chi\omega_A).
$$

这些给出了上述复重构所需的 \(\nabla z=\nabla z_3-\nabla o\)。数值实现所用的复半径下限在其下限之下携带零半径导数，并且它本身绝不会独自确立一个被接受的根。

令 \(d\) 为由此得到的四个驱动式，\(j(H)\) 与 \(c(H)\) 为明度系数与 log2 彩度系数，\(g\) 为全局 log2 彩度增益，\(S=\max(100,H_g)\) 为固定观测尺度。两个残差与 Jacobian 行为

$$
r_0=\frac{H+j(H)\cdot d-H_3}{S},\qquad
r_1=\log(R/C)-\log(2)\,[g+c(H)\cdot d],
$$

$$
\nabla r_0=\frac{\nabla H+(j'(H)\cdot d)\nabla H+j(H)\cdot\nabla d-\nabla H_3}{S},
$$

$$
\nabla r_1=\nabla\log R-(0,1)
 -\log(2)\bigl[(c'(H)\cdot d)\nabla H+c(H)\cdot\nabla d\bigr].
$$

每次试探仍然计算实际残差，每个被恢复的 RGB 候选仍然要通过对完整正向模型的复现检查。解析导数改变的是求解器开销，而不是被接受的正向函数、迭代上限或诊断容差。

满足 \(\lVert r\rVert_\infty\le2\times10^{-11}\) 的行会离开活跃池。正则归约允许 24 次迭代。带符号/fallback 以及其他未解析的目标使用全正向 RGB 细化，每个种子允许 30 次迭代。对于目标 \(y\)，其坐标表示

$$
\rho=\max(10^{-7},\lVert y\rVert_\infty),\qquad
x_N=\operatorname{clip}(\rho v,-2^{20},2^{20}),\qquad
r(v)=\frac{N(x_N)-y}{1+\lVert y\rVert_\infty}.
$$

搜索坐标另外被界定在 \([-10^{14},10^{14}]^3\)。相对于目标的**线性**坐标取代了此前的 asinh 求解器坐标；LUT 中非负的 log1p *地址 shaper* 是一个独立的采样选择。每次细化试探仍然求值完整的 float64 正向方程。

#### 候选选择与诊断

1. 构造正则候选，把它裁剪到搜索域，并测量其完整正向残差 \(\epsilon_N\)（定义见下文）。若 \(\epsilon_N\le2\times10^{-10}\)，立即优先采用它。
2. 对于未解析/非有限的结果，把未改变的目标作为恒等/fallback 候选来测试。仅当其有限残差更小时才保留它。
3. 对仍高于 \(2\times10^{-10}\) 的行，细化当前最优候选。仅当结果改善了已测量的残差时才保留这个有限结果。
4. 对于剩余的行，把目标种子与半目标种子放进同一个合并池中一起求解。先考虑以目标为种子的结果。仅当该行仍高于 \(2\times10^{-10}\) 时才考虑半目标结果。只保留有改善的结果。

这里没有经过时间上限、没有上一次烘焙的热启动、没有邻域正则化项，也没有粗采样的初始化器。对于固定的数值输入/环境，该策略是确定性的；它不是穷举式求根，也不构成全局最小值证明或跨折叠的连续性保证。它可能选择与 1.14.0 版本不同的合法原像。求解器策略被纳入 LUT 签名。

存储的诊断容差有意比内部停止阈值更宽松：

$$
\epsilon_N=\frac{\lVert N(\hat x_N)-y\rVert_\infty}
                   {1+\lVert y\rVert_\infty}\le2\times10^{-8}.
$$

高于该阈值的采样仍是尽力而为的采样，并会被显式计数；最差残差存储在打包后的 LUT 图像上。诊断统计的是返回的顶点，而不是种子尝试次数。float32 存储误差与顶点间插值误差分别测量。精确的恒等 bypass 会原样保留带符号/HDR 输入。

#### 已安装的 GPU 求值剖面

运行时用 Blender 的 `GPUShaderCreateInfo` 编译内嵌于 Python 的源码。一次 compute 调用通过完整启用的序列对一个格点顶点求值。正向函数使用相同的解析 Tone、modCAM16、p=2 \(C/J_A\) 驱动式、3×6 contribution、concentration、Hue、Adaptance、H–K guard、带符号 lift 与 fallback 方程，并以 float32 求值。其中没有中间的 Quintic 曲线或 Grade LUT。

对于每个逆条目，正则的 \((\log J_2,\log C_2)\) 求解使用实测的有限差分 Jacobian 与阻尼 Broyden 更新，最多 24 次迭代，并采用上文显式的双变量正规步。固定参考的 H–K 与 Tone 逆使用按 float32 缩放的带保护标量 Newton 策略。完整的正向 RGB 恢复依次尝试正则候选、恒等种子与半目标种子，每个最多 24 次三变量迭代。CPU 的解析正则 Jacobian 与更严格的停止阈值不被声称适用于本 profile。

1.23.2 版本在向量列上求值完整的二维与三维 Broyden 更新。令 \(D\)、被接受的位移 \(s\) 与残差变化 \(z\) 如上文定义，并令 \(D_{:,i}\) 表示第 \(i\) 列。则

$$
(D_{new})_{:,i}=D_{:,i}+\frac{((z-Ds)s_i)}{s^Ts},\qquad
i=0,\ldots,n-1,\quad n\in\{2,3\}.
$$

GPU 在 \(s^Ts\le10^{-20}\) 时省略该贡献。每一列的乘法、除法与加法都在 `vec2` 或 `vec3` 上求值，然后由这些列构造更新后的矩阵。这既避开了未声明的 `outerProduct` 内建函数，也避开了所报告的 Blender Metal 编译器拒绝的矩阵/标量除法。它保持先乘后除的顺序、数学上的更新以及现有的 GPU 停止策略。

令 \(y\) 为某个逆条目的目标，\(\hat x\) 为其被选中的候选，\(F_{32}\) 为该条目的完整 float32 正向函数。定义

$$
s_{\mathrm G}(y)=\max(10^{-12},\lVert y\rVert_\infty),\qquad
e_{\mathrm G}=\frac{\lVert F_{32}(\hat x)-y\rVert_\infty}{s_{\mathrm G}(y)},
\qquad \tau_{\mathrm G}=3\times10^{-6}.
$$

这个相对尺度可保留小幅的暗部调整。若配上这个 float32 阈值使用 \(1+\lVert y\rVert_\infty\)，就会在接近黑处允许很大的相对误差。返回的候选要对照完整正向操作接受审核。设备在使用了 RGB 恢复时记录一个顶点位，在任一逆条目仍未解析/非有限时记录另一个顶点位。其最终未解析审核保守地用 RGB 欧几里得范数对照 \(\tau_{\mathrm G}s_{\mathrm G}\)，因此它可能标记出某个通过了无穷范数停止测试的顶点。

对每个被标记的顶点，主机通过 float64 CPU 路径重新求值**整个 Stack**，包括所有矩阵与 Bradford 连接，然后存储该替换值。来自有界 GPU 批次的被标记顶点，在每个预览/细化阶段共享一个 CPU 恢复池。未被修复的值是私有的，无法发布。它不会在 CPU 上细化或验证每个未被标记的顶点。剩余的不可有限输出会中止 GPU 烘焙并选择 CPU 恢复。奇异逆矩阵直接走 CPU 伪逆路径。

cube 的策略标识符是 `analytic-f32-relative3e-6-audited-v1`。诊断记录 GPU 采样/搜索/标记计数、被修复的 CPU 顶点以及修复时间。CPU 近似/残差字段只描述被修复的顶点；它们并不为未标记的 GPU 网格确立 CPU 的 \(2\times10^{-8}\) 诊断容差。LUT 插值与外插仍是独立的误差。

输入/输出 AP1 坐标转换与最终存储是主机操作；每次 GPU 派发上传一份数值参数快照，并读回一个有界的顶点批次。33³/65³ 这一对仍然精确求值 274,625 个顶点，并逐位复用共同的 float32 值。若某个已发布的匹配 GPU 预览必须在 CPU 上完成，细化会保留这些共同值，只计算其余的顶点。由 CPU 完成的 cube 会在 `gpu_preview_*` 字段下保留这些预览审核结果；其 CPU 残差计数只覆盖 CPU 求值的工作。参见[运行时调度](architecture.md#gpu-上下文调度与恢复)与[验证](testing.md#已安装-gpu-烘焙1230)。

### 18.2 普通 Grade 的方向与矩阵位置

对于 Grade \(g\)，令 \(M_g\) 为 Stage 1，\(N_g\) 为其完整的解析非线性变换。定义
$$
F_g(x)=N_g(M_gx),\qquad
I_g(y)=M_g^\dagger\,\widehat{N_g^{-1}}(y).
$$
当条件数至多为 \(10^{12}\) 时，这里 \(M_g^\dagger=M_g^{-1}\)；否则它是相对奇异值截断为 \(10^{-12}\) 的 Moore–Penrose 伪逆。后者显式地是近似的。它不必最小化完整的 grade 残差，因为非线性候选可能并不落在该奇异矩阵的值域之内。

在标准 grading 坐标中，普通 Grade 节点总是施加其 Grade 正向。其 Baked LUT 路径求值 \(\widehat{\mathcal N}_g(M_gx)\)：Stage 1 在非线性 cube 之外保持精确。其节点局部的 Render Method 选择 Baked LUT 或 Direct。逆由 Stack 条目施加（包括单条目 Stack），并且其完整的矩阵逆被烘焙进该 Stack 的 cube 里。共享的 Grade 数据既不存储方向，也不存储渲染方法。第 19.5 节规定了原生 ACEScg 坐标的变化。

### 18.3 Stack 组合与最终单一 cube

一个 Stack 拥有共享 Grade 引用的有序列表，以及启用状态与方向。空条目与被旁路的条目被省略。这里 \(i=1,\ldots,m\) 按顺序枚举启用且已填充的条目，\(d_i\) 选择 \(F_{g_i}\) 或 \(I_{g_i}\)。该列表属于其节点局部；Grade ID 仍保持共享。定义

$$
T_i=\begin{cases}F_{g_i},&d_i=\mathrm{forward},\\I_{g_i},&d_i=\mathrm{inverse},\end{cases}
\qquad \mathcal S_{\mathrm{stack}}=T_m\circ\cdots\circ T_1.
$$

这里 \(T_i\) 表示一整个 Grade 条目，有别于前文定义的 Stage 2 算子 \(T\)。令 \(B_{\mathrm L}\) 把标准 grading RGB 转换为原生 ACEScg/ACES 白；第 19.1 节定义了其矩阵。对于固定的非负 log1p 轴 \(a_j\)（\(0\le j<65\)），烘焙

$$
V_{ijk}=\operatorname{float32}\!\left[
 B_{\mathrm L}\,\mathcal S_{\mathrm{stack}}\!\left(B_{\mathrm L}^{-1}[a_i,a_j,a_k]^T\right)
\right].
$$

每个 \(T_i\)（包括其矩阵）在每个 CPU 采样点上以 float64 运行，或通过上文所述的解析 float32 GPU profile 运行，并带有被标记的整 Stack CPU 恢复。不采样任何中间 3D LUT 或 Quintic 近似。条目之间不额外施加任何钳制。空行与被旁路的行被跳过；没有任何启用 Grade 的序列即为恒等。运行时对 \(V\) 求值一次物理线性 ACEScg 的四面体插值；alpha 绕过该变换。

网格为 \([0,1024]^3\) 上的 \(65^3\)，地址 0 处为零，每个分量有 64 个正格。其普通 log1p 常数为 \(k=0.01\)。[Direct 与采样求值](../theory/lut.md)定义了该地址曲线及其逆。此段描述当前共享采样器：先将 RGB 修复进立方体，再计算有界地址与比例，并非逐通道保持边缘值。归档 1.23.2 采样器使用其记录的定义域与外推规则。存储的输出值仍为带符号线性 ACEScg/ACES 白。CPU/Shader 插值器使用等价的顶点差分形式。合成器存储把一张基础平面与三张正向轴差分平面各自用 RGBE 独立编码；它读取一个基础与三条有序边，并用融合乘加累加物理分数。这是一种 LUT 表示，而不是四个串联的变换。减少插值次数并不构成普遍意义上的精度提升：复合后的函数可能有更尖锐的曲率，或存在所选逆的不连续点。

Stack 签名包括采样基、网格边界、形状常量、求解器策略/版本，以及按顺序排列的启用条目及其方向、Grade 白与三个阶段各自的设置。被跳过的条目不参与。Blender 场景空间只影响外层矩阵。名称与编辑器焦点被排除在外。Stack 诊断验证完整的逆条目（包括其矩阵），并单独统计奇异矩阵。

### 18.4 运行时与验收证据

Stack 编辑首先求值一个嵌套的 \(33^3\) 网格。令 \(a_i\)（\(0\le i\le64\)）为上文所述最终轴。定义预览轴 \(b_j=a_{2j}\)（\(0\le j\le32\)）与预览顶点数组 \(U\)。对于相同的不可变 Stack 参数，

$$
U_{ijk}=\operatorname{float32}\!\left[
 B_{\mathrm L}\,\mathcal S_{\mathrm{stack}}\!\left(B_{\mathrm L}^{-1}[b_i,b_j,b_k]^T\right)
\right],\qquad V_{2i,2j,2k}=U_{ijk}.
$$

定义剩余的索引集合

$$
\mathcal R=\{0,\ldots,64\}^3\setminus
\{(2i,2j,2k):0\le i,j,k\le32\}.
$$

在细化过程中只有 \(\mathcal R\) 中的顶点会被解析求值。因此 \(33^3=35{,}937\) 个采样产生预览，而 \(|\mathcal R|=65^3-33^3=238{,}688\) 个额外采样完成最终 cube。共享的 float32 采样被逐位保留；最终顶点绝不会由预览插值而来。逆诊断在这些互不相交的集合上累加，因此每个最终顶点对每个逆条目只计数一次。预览插值使用物理端点 \(b_j,b_{j+1}\)；最终插值使用 \(a_i,a_{i+1}\)。两者都使用四次四面体读取，以及相同的场景适配器、带符号外插与 alpha 处理。

预览每个分量有 32 个正格，且没有负采样分支。两个层级都使用 1024 像素的图集宽度；Shader 原始顶点图集的高度分别为 36 与 269。合成器的单图像基础/边图集有四张平面，高度分别为 141 与 1073。它独立打包基础与正向差分以避免半浮点相减误差，同时每次查找仍保留四次读取。打包图像携带其网格尺寸与特定于分辨率的签名；原生地址核与 scope 缓存使用已安装的分辨率。改变分辨率并不会组合两个 LUT。

首次预览在 40 ms 之后变得可用，且不会因每次鼠标事件而重启该延迟。单个 CPU worker 接收不可变的 NumPy 数据，且从不访问 Blender 对象；GPU 派发使用主线程绘制上下文与定时器发布。在连续编辑期间，一个在飞的预览可以完成，并按其捕获的参数被安装，而更新的编辑则合并为一个最新的后继者。预览不能替换当前参数下已安装的最终 cube。细化在无编辑 300 ms 之后才开始，且只针对匹配的已完成预览。CPU 逆阶段使用一个共享的未解析池，在整个阶段内保持压实，而不是拆成互不相干的小批次。GPU 顶点独立完成其有界求解，并对被标记者执行整 Stack 的 CPU 恢复。正向求值则为剩余顶点保留有界块。

编辑会在协作检查点上取消过时的最终工作。移除与拆除会取消排队中的任务。任意的过时任务与每个过时的最终 cube 都会被拒绝；在连续编辑期间，只有被跟踪的在飞预览可以暂时落后于控件。两个 scope 与原生输出读取同一个已安装 cube，并在预览与最终发布时刷新。在首次预览之前，使用一条清晰标记的恒等路径。渲染准备与常规保存会同步完成最新的 **65³** 烘焙，即使已安装预览或仍有较旧的预览在飞；待处理的前台 GPU 工作在 CPU 上完成。烘焙错误会被上报。该扩展使用 Python、Blender 自带的 NumPy 与 Blender 自身的运行时着色器编译器，不含任何外部预编译包或原生扩展二进制。

`test_progressive_lut.py` 验证嵌套坐标、共享顶点的精确复用、互不相交的工作计数、取消以及逆诊断。Stack 编辑测试套件覆盖原生 33³/65³ 输出、scope 失效、连续编辑合并、节点移除与最终质量同步。`benchmark_progressive.py` 相对独立的 65³ 烘焙测量首次预览与总数值延迟。

`test_inverse_math.py` 针对独立的标量推导、带符号/正值的完整正向复现、矩阵顺序、确定性求值以及奇异矩阵诊断来验证向量 guard。`test_inverse_solver.py` 检查标量 Newton 的兜底逻辑、tone 导数、优化/参考正向一致性、割线求解、整格调度、取消与进度。`test_grade_stack.py` 演练真实的 Blender 所有权、共享编辑、过时完成结果拒绝、协作式 worker 取消、原生 Shader/Compositor 查找与 alpha、动画、保存/加载、禁用扩展后的外观，以及仅正向的普通节点。`test_shared_grade_undo.py` 演练条目方向与旁路的真实撤销/重做，同时保持普通 Render Method 独立。`evaluate_inverse_precision.py` 测量存储的 IMG_* 夹具以及合成带符号/HDR 输入的格点外误差。`benchmark_inverse.py` 测量新的数值烘焙，且不使用已完成的 LUT 缓存。精度与性能报告随实现一同提供。既有的独立推导测试保留在原处。`test_stack_editing.py` 通过 Blender 夹具运行器运行新增的 RNA、紧凑 UI、示意图手势、已安装 LUT 的 scope 以及原生持久化回归测试。

## 19. 共享 Grade 白点、权威矩阵与固定 LUT 坐标

本节是 Blender 1.21.0 的契约。不存在面向旧工程的数据迁移或滑杆导入路径。DCTL 保留其现有的 Destination White 行为，并且不执行任何自动的存储矩阵转换。其经 CAT16 适配的红/蓝锚点保持不变。

### 19.1 附加符号与 Bradford 变换

所有矩阵都作用于列向量。白点归一化为 \(Y=1\)。

| 符号 | 含义 |
| --- | --- |
| \(W_0\) | D65，\(xy=(.3127,.3290)\)，固定的规范调色白点 |
| \(W_{\mathrm L}\) | ACES 白点，\(xy=(.32168,.33767)\)，固定的 LUT 边界白点 |
| \(W_g\) | 共享 Grade \(g\) 所选定的工作白点；默认为 \(W_0\) |
| \(W_r\) | 已存储的 Stage 1 系数所记录的参考白点 |
| \(B\) | Bradford XYZ 到锥体矩阵，与第 2 节中的 CAT16 \(A\) 不同 |
| \(C_{a\to b}\) | 从白点 \(W_a\) 到 \(W_b\) 的 Bradford 适配 |
| \(P_0\) | 第 3.1 节中的标准线性 Rec.709/D65 RGB 到 XYZ 矩阵 |
| \(P_g=C_{0\to g}P_0\) | 对 Grade \(g\) 而言规范调色 RGB 的 XYZ 解释 |
| \(P_{\mathrm L}\) | 归一化到 ACES 白点的原生 ACEScg/AP1 RGB 到 XYZ 矩阵 |
| \(B_{\mathrm L}=P_{\mathrm L}^{-1}C_{0\to\mathrm L}P_0\) | 规范调色 RGB → LUT RGB，包含 D65 到 ACES 的 Bradford 适配 |
| \(M_{g,r}\) | 权威存储的 Stage 1 XYZ 矩阵，包含曝光，记录于 \(W_r\) |
| \(M_{g}=C_{r\to g}M_{g,r}C_{r\to g}^{-1}\) | 在所选 Grade 白点下表达的 Stage 1 XYZ 矩阵 |
| \(L_g=P_g^{-1}M_gP_g\) | 固定调色 RGB 坐标下的 Stage 1 |
| \(A_s\) | 从当前场景 RGB 到线性 Rec.709/D65 的 Blender 原生转换 |
| \(N_g\) | 使用 \(P_g,W_g\) 的完整 Stage 2+3 求值器，位于固定 RGB 坐标 |

Bradford 矩阵为

$$
B=\begin{bmatrix}
 .8951& .2664&-.1614\\
-.7502&1.7135& .0367\\
 .0389&-.0685&1.0296
\end{bmatrix},\qquad
C_{a\to b}=B^{-1}\operatorname{diag}\!\left(\frac{BW_b}{BW_a}\right)B.
$$

对于受支持的、锥体为正的白点预设，该矩阵可逆，并且

$$
C_{b\to a}=C_{a\to b}^{-1},\qquad
C_{b\to c}C_{a\to b}=C_{a\to c}.
$$

预设包括 D65、日光 D60 \((.32161671,.33761992)\)、ACES \((.32168,.33767)\)、D50 \((.34567,.35850)\)、D55 \((.33242,.34743)\)、D75 \((.29903,.31488)\)、DCI \((.314,.351)\) 以及等能 E \((1/3,1/3)\)。Blender 不提供自定义工作白点 xy。该预设与 Grade 共享；方向与启用状态属于 Stack 条目；Render Method 属于普通 Grade 节点。

在 Blender 主线程上，对三个单位 RGB 向量采样 `mathutils.Color.from_scene_linear_to_rec709_linear()`，以取得 \(A_s\) 的各列。这会使用当前生效的 Blender/OCIO 色域与白点转换。实现使用来自同一矩阵的 \(A_s^{-1}\)，而不是把独立取整的正向与反向探测组合起来。对于原生 Linear Rec.709，\(A_s=I\)。缓存失效覆盖文件重新加载与工作空间变更。worker 收到的只是数值快照，绝不会是 Blender API 对象。

### 19.2 场景边界处完整的正向与逆向

用 \(P=P_g\) 和 \(W_d=W_g\) 来解释第 3–9 节的分量方程。所有 CAT16、H–K、tone、chroma-driver、Hue/Concentration、signed-lift 与回退规则依然生效。完整的解析正向调色为

$$
\boxed{F_{g,s}(x_s)=A_s^{-1}\,N_g\!\left(L_g A_s x_s\right).}
$$

所选的半解析逆为

$$
\boxed{I_{g,s}(y_s)=A_s^{-1}\,L_g^\dagger\,
       \widehat{N_g^{-1}}\!\left(A_s y_s\right).}
$$

伪逆阈值与候选策略即第 18 节所述。伪逆的最小范数定义在固定调色 RGB 基上，而不是在各个 Blender 场景色域中分别定义。负 RGB 会穿过两个场景矩阵被保留。

对于 \(W_g\) 处概念性的 XYZ 非线性函数 \(\mathcal N_g\)，

$$
N_g(r)=P_g^{-1}\mathcal N_g(P_g r),\qquad
P_gN_g(L_gr)=\mathcal N_g(M_gP_gr).
$$

因此 RGB 实现恰好就是：按要求适配到 Grade 白点，在那里完成全部调色，再适配回来。非线性模型的 `to_cone` 与 `from_cone` 已经包含 \(P_g\) 和 \(P_g^{-1}\)；不要把这两个适配再加一遍。

若 \(x_t=T_{s\to t}x_s\) 表示同一颜色在另一场景空间中的形式，则一致的场景坐标变换为 \(T_{s\to t}=A_t^{-1}A_s\)。于是

$$
F_{g,t}(T_{s\to t}x_s)=T_{s\to t}F_{g,s}(x_s).
$$

除浮点求值差异外，同一关系对所选的逆以及固定采样 LUT 同样成立。Grade 矩阵、其选定的白点、Tone/Color 取值以及 LUT 签名都不因 Blender 场景空间切换而改变。输入颜色自身必须完成转换；不同 RGB 空间中数值完全相同的三元组并非等价颜色。

### 19.3 白点变更与矩阵存储

对于显式的 Grade 白点变更 \(W_a\to W_b\)，通过下式保留其校正：

$$
\boxed{M_b=C_{a\to b}M_aC_{a\to b}^{-1}.}
$$

由于 \(P_b=C_{a\to b}P_a\)，在精确算术下 \(L_b=L_a\)。因此 Stage 1 保留其色彩作用，尽管其源白点、曝光与方向性编辑读数可能发生变化。Tone/Color 参数在数值上保持不变。一般而言 \(N_b\ne N_a\)：改变外观上下文并不会保持非线性的创作操作。

Grade 存储九个双精度 XYZ 系数和一个记录的白点，而不是九个权威滑杆值。对于未做动画的矩阵，改变白点会存储共轭后的矩阵并更新其记录白点。当矩阵存在动画时，则保留系数及其记录白点：在每一帧上求值 \(C_{r\to g}M_{g,r}(t)C_{r\to g}^{-1}\)。这是围绕被求值矩阵的一个常量坐标转换，因此它涵盖任意插值关键帧、NLA 与驱动器，而无需重写动画曲线。新的编辑在存储之前会被转换回记录基。

线性自动关键帧会记录全部九个矩阵系数。计算出的滑杆读数没有独立的动画通道。矩阵插值一般不等于曝光档位、源 xy 或朝向角上的插值。复制 Grade 会像以前一样独立复制其生效 Action。完整执行 Linear 重置会存储单位矩阵，即使编辑读数只是近似时也是如此。

### 19.4 从常规矩阵推导 Stage 1 控件

令 \(w=\operatorname{XYZ}(W_g,1)\)、\(M=M_g\)。方向矩阵固定 \(w\)，而创作性的 CAT16 矩阵把它的源白点映射到 \(w\)。因此，在常规可表示的情形下，

$$
u=M^{-1}w,\qquad k=1/u_Y,\qquad e=\log_2 k,
\qquad W_s=u/u_Y,\qquad (x_s,y_s)=\operatorname{xy}(u).
$$

完全按照第 3.2 节构造创作性 CAT16 矩阵 \(K=\operatorname{CAT16}(W_s\to w)\)。于是

$$
D=k^{-1}MK^{-1},\qquad Dw=w.
$$

对于未改动的、已适配的 Rec.709 锚点 \(p_i\)，定义 \(v_i=D\operatorname{XYZ}(p_i,1)\)、\(q_i=\operatorname{xy}(v_i)\)、\(a_i=p_i-\operatorname{xy}(w)\) 以及 \(b_i=q_i-\operatorname{xy}(w)\)。内部的 Balance、Spread 与 Heading 为

$$
\beta_i=\log_2(v_{i,Y}),\qquad
s_i=100\left(\frac{\lVert b_i\rVert}{\lVert a_i\rVert}-1\right),\qquad
\theta_i=\frac{180}{\pi}\operatorname{atan2}
(a_{i,x}b_{i,y}-a_{i,y}b_{i,x},a_i\cdot b_i).
$$

UI 将 \(-\beta_i\) 显示为 Balance。该分解要求有效的正亮度与一个可接受的源白点；为精确重建，target-y 构造的保护也必须处于未激活状态。

对于奇异矩阵，实现使用最接近白点的最小二乘原像，

$$
u=w+M^+(w-Mw),
$$

并在可能时给出有限的编辑值。无效的增益/xy 使用 `linear.decompose` 中已记录的有限中性回退值。这类数值只是编辑视图。计算归一化的矩阵重建残差

$$
\epsilon_{\mathrm{UI}}=
\frac{\lVert M-f(p)\rVert_{\max}}{1+\lVert M\rVert_{\max}},
$$

其中 \(f\) 由推导出的控件 \(p\) 构造 XYZ 矩阵。若 \(\epsilon_{\mathrm{UI}}>2\times10^{-8}\)，则显示近似读数提示。在读取、刷新、scope 求值或场景变更期间，绝不要用 \(f(p)\) 覆盖 \(M\)。常规控件编辑 \(p\to p'\) 通过下式保留不可表示的余项：

$$
M'=M+f(p')-f(p).
$$

仅修改曝光的编辑则改用 \(M'=2^{e'-e}M\)，从而保留所有既有的矩阵结构。取消手柄手势会恢复精确的矩阵快照。源白点编辑使用现有的可接受域投影；转换后的读数可能落在常规滑杆软范围之外，但不会因此钳制所存储的矩阵。

### 19.5 LUT 边界与混合白点 Stack

每个扩展立方体都具有**固定的原生线性 ACEScg/ACES 白点输入与输出坐标**。规范调色 RGB 仍然是经由 \(P_g\) 解释的线性 Rec.709；改变采样基不得改变 Grade 模型、锚点、白点、矩阵或控件。LUT 边界处的 ACES 白点并非物理显示假设，也不限制 Stack 内部各 Grade 的白点。

设 \(f\) 为以规范调色坐标表达的任意完整非线性函数。定义其 LUT 坐标表示与存储顶点数组为

$$
f_b(z)=B_{\mathrm L}f(B_{\mathrm L}^{-1}z),\qquad
V^f_{ijk}=\operatorname{float32}\!\left(f_b([a_i,a_j,a_k]^T)\right).
$$

将 \(\mathcal C_b[f](z)\) 定义为 \(V^f\) 在原生 ACEScg 输入 \(z\) 处的物理线性 RGB 四面体插值。下标 \(b\) 标识采样基；它与外观坐标标量 \(b\) 无关。因此 \(B_{\mathrm L}^{-1}\mathcal C_b[f](B_{\mathrm L}r)\) 近似于 \(f(r)\)，而不改变其含义。

普通 Grade 节点求值正向 LUT 路径：

$$
\boxed{
 y_s=A_s^{-1}B_{\mathrm L}^{-1}\,
 \mathcal C_b[N_g](B_{\mathrm L}L_g A_s x_s)
}
$$

Stage 1 留在普通立方体之外。原生 LUT 分支把 \(B_{\mathrm L}L_gA_s\) 合并为一个输入矩阵，把 \(A_s^{-1}B_{\mathrm L}^{-1}\) 合并为一个输出矩阵。Direct 则分别使用 \(L_gA_s\) 与 \(A_s^{-1}\)。普通 Baked LUT 节点在烘焙期间可以使用其当前的 Direct 求值。当替换尚未完成时，Stack 图像输出与 scope 使用已安装的完整 Stack LUT。

对于已启用、已填充的 Stack 条目 \(i\)，依据 Direction 使用规范坐标下的正向映射 \(G_i(r)=N_i(L_ir)\) 或所选的逆 \(G_i(r)=L_i^\dagger\widehat{N_i^{-1}}(r)\)。于是

$$
\mathcal S_{\mathrm{stack}}=G_n\circ\cdots\circ G_1,\qquad
\boxed{
 y_s=A_s^{-1}B_{\mathrm L}^{-1}\,
 \mathcal C_b[\mathcal S_{\mathrm{stack}}](B_{\mathrm L}A_s x_s).
}
$$

解析烘焙包含每个条目的 Stage 1、非线性操作与逆选择，不产生中间 LUT。相邻的 Grade XYZ 上下文通过

$$
P_{i+1}P_i^{-1}
=C_{0\to i+1}C_{0\to i}^{-1}
=C_{i\to i+1},
$$

连接，即它们所选白点之间的 Bradford。这一连接隐含在相继的坐标感知求值器中。若在它们的规范 RGB 输出之间再加一个 CAT，就会对该序列重复适配。

立方体形状与 Blender 的工作空间无关。场景空间变更会更新 \(A_s\) 及其组合出的原生矩阵，并复用该立方体。Grade 白点变更会修改被烘焙的函数，并使受影响的普通与 Stack 立方体失效。所选白点也参与 scope 与模型缓存的键。Alpha 绕过这些 RGB 操作。

D65 是选定的内部调色默认值。这些场景线性节点仍位于视图变换之前。D65 并不会使处理变为显示参考、选择某种编码，或覆盖 ACES 的创作白点。已保存的原生节点图保留其最后一次求值的矩阵；在扩展被禁用时改变场景空间不会更新它们。

### 19.6 采样选择与实现证据

当前参考／共享网格使用原生 ACEScg/ACES 白点、边界 \([0,1024]\)、64 个正向单元以及普通 log1p \(k=0.01\)。输入在寻址前修复到立方体内，有界比例从修复后的 RGB 求得；存储输出仍可带符号。这是当前配置对比，并非 1.23.2 的输入策略；数值稳定的顶点差分插值器定义在 [Direct and sampled evaluation](../theory/lut.md) 中。整形函数与采样空间是由域研究在其 \(+128\) 个入围方案中选出的；边界是在研究之后才提高的，因此该研究的误差数字描述的是它自己的域，而非这里的域。编码 RGB 目标会选出另一条曲线。[domain study](lut-domain-study.md) 记录了两个目标、实验输入与实测局限性。

生产验证使用 `test_lut_study.py`、`test_cube_math.py`、`test_cube_native.py`、`test_lut_grid_regression.py`、`test_working_white.py` 以及原生渲染测试夹具。`evaluate_lut_sampling.py --production` 在每个已存储的 IMG_* 像素上，通过全部四个所要求的 ACES 2.0 输出测量实际的 Baker/Cube 路径。求解器残差、基协方差、原生图传输与越网格插值误差仍然是彼此独立的测量。

### 19.7 Stack 检查与编辑

对于 Stack 输入 \(x_s\)，对已安装的立方体及其实际原生矩阵求值以得到 \(y_s\)。设 \(\Phi_g(r)\) 为所选 Grade 的外观测量，包含其白点与参考设置，但不施加任何创作性调色。Tone scope 测量 \(J_{\mathrm{in}}=[\Phi_g(A_sx_s)]_J/100\) 与 \(J_{\mathrm{out}}=[\Phi_g(A_sy_s)]_J/100\)。所显示的色调曲线与可编辑手柄属于 Grade \(g\)。Stage 3 图像统计在同一所选上下文中分析 Stack 输出。待处理的烘焙不会运行解析采样图像预览。当相匹配的已安装立方体发生变化时，scope 会刷新。这些诊断不会改变渲染变换。

## 20. 参考逆

第 10–18 节反演的是 1.23.2 的生产阶段：一个带解析色相消元的双未知量重建、一个带保护的标量 guard 逆，以及一个池化的阻尼 Broyden 精化。解析参考采用另一种思路。它根本不对 Stage 3 做逐分量反演。它搜索完整正向函数的原像，并通过运行该正向函数来验证每一个候选。

本节描述 `libraries/perceptual-grade-reference/src/inverse.py` 以及 `src/stack.py` 中独立的 Stack oracle。当问题涉及参考实现时，请阅读本节而不是第 10–18 节；当问题涉及已发布的 DCTL 或 Blender 逆时，请阅读那几节。

### 20.1 契约

入口为 `solve(model, xyz, forward=None)`，返回 `InverseResult(value, residual, status)`，包含三个逐行数组。`value` 是模型调色上下文中的 XYZ；规范 RGB 仅用于内部搜索与排序，`residual` 是缩放后的最大残差，`status` 为下列之一：

| 状态 | 含义 |
| --- | --- |
| `root` | 某候选在缩放的无穷范数下以 `2e-10` 复现了其目标 |
| `approximate` | 没有候选达到该容差；返回通过验证的最佳候选及其实际残差 |
| `invalid` | 输入行非有限，未尝试任何候选 |

“规范”指的是**在这次搜索所找到的根之中**最接近线性的那个。模块文档字符串明确指出：固定的搜索配置不会枚举所有根，也不证明任何可达性性质。返回的 `root` 是经过验证的原像；但一个 `root` 集合并不被声称是完备的。

### 20.2 搜索坐标与边界

搜索在 `arcsinh` 规范 RGB 中进行，这使得步长在远离零处大致按对数缩放，并使近黑行为保持良态。在求值之前，一切都被裁剪到盒 \(|x| <= 2^20\)。有限差分步长为

$$
h_i = \sqrt[3]{\varepsilon}\,(1+\lvert z_i\rvert),
$$

其中 \(\varepsilon\) 是 binary64 机器 epsilon。立方根步长随搜索坐标缩放，在中心差分的截断误差与浮点舍入误差之间取平衡，并不保证固定数量的准确数字。

### 20.3 种子

每一行都从一组经过合并与去重的起点出发：

1. **线性先验**——经由 Stage-1 矩阵得到的最小二乘解；在没有非线性操作生效时它是精确的。
2. **目标**本身与**零向量**。
3. 先验的 \(1/4, 1/2, 2, 4\) 倍的**缩放先验**，用于覆盖曝光猜错的情形。
4. 位于 \(prior \pm \mathrm{scale}\) 的 **\(3^3\) 偏移模板**，其中 scale 为 \(\max(1, \lVert prior\rVert_\infty, \lVert target\rVert_\infty)\)。当线性先验落入错误的吸引域时，正是它恢复了原像。
5. **解析中性原像**。负的非彩色轴具有一个平方根色度尖点，平滑搜索可能在附近停滞，因此中性情形被直接求解：解码目标的非彩色响应，对色调曲线求逆以得到幅度，并重建中性 RGB。它仍然像其他每个种子一样经过同一套正向验证，因此它只是一个更好的起点，而不是可信的答案。

当 Stage 1 是精确的标量增益、且其余一切均未激活时，中性种子会退化为精确的三通道原像。

### 20.4 迭代

各候选以相互独立的阻尼因子并行推进——即把 Levenberg–Marquardt 步表达为增广最小二乘问题，而不是求解正规方程：

$$
\Delta = \operatorname{lstsq}\!\left(\begin{bmatrix}J\\ \sqrt{\lambda}I\end{bmatrix},\begin{bmatrix}r\\ \mathbf 0\end{bmatrix}\right),
\qquad z \leftarrow \operatorname{clip}(z-\Delta,\ \pm\arcsinh 2^{20}),
$$

其中 \(J\) 是缩放残差的中心有限差分 Jacobian。阻尼从 \(10^{-3}\) 开始，在接受步上乘以 \(1/3\)，在拒绝步上乘以 \(10\)，并裁剪到 \([10^{-12},10^{12}]\)。当候选的缩放残差降到 `TOLERANCE/10` 以下、其阻尼达到上界、其步长降到 \(2\times10^{-13}\) 以下，或经过 128 次迭代后，该候选停止。迭代上限是安全边界，而不是预期开销：通常残差检验会先终止。

接受检验要求残差平方和严格下降。不使其下降的步会被拒绝，其阻尼随之增大，因此停滞的候选会退让，而不是漫游。

### 20.5 接受与排序

当

$$
\max_i\bigl|r_i\bigr| \le \texttt{TOLERANCE} = 2\times10^{-10}
\quad\text{on}\quad
r = \frac{\text{forward}(x)-\text{target}}{1+\lVert\text{target}\rVert_\infty}.
$$

时，候选成为 `root`。正是相对缩放使该容差对极暗与极亮的目标都同样有意义；绝对容差在一种情形下无法达到，在另一种情形下则形同虚设。

排序因结果而异，而这一区别很重要：

- **当存在任何根时**，根按到先验的 \(\arcsinh\) 距离排序，因此最接近线性的根胜出，结果保持在最小二乘预览附近。
- **当不存在根时**，候选先按残差排序、再按先验距离排序，因此所报告的近似是所能获得的最佳复现，而不是最近的那个。

剩余的并列由 RGB 字典序打破。这一点很重要，因为多个种子可能收敛到同一个根，而坐标在比特层面并不相同；若没有该打破并列的规则，被选中的取值就会依赖种子顺序与批次构成，同一输入在不同批次形状下可能返回略有不同的输出。

### 20.6 不嵌套 guard 逆

每个候选的残差都求值**完整正向导出**：候选提供其自身冻结的 Tone 后参考能量，阶段 3 随后执行 Adaptance → H–K 修复 → 公共正值 Scale，最后才进行 RGB 立方体包含。搜索从不嵌套独立的保护逆，不构建保护查找表，也不会在导出处重复 H–K 修复。

这是有意为之。在被反演量已知之前，色调后参考能量是未知的，所以固定参考的 guard 逆在某个候选提出该参考之前毫无意义。逐分量反演需要猜一个参考，而猜错只会产生一个终究无法通过验证的候选。

立方体投影是另一回事：它是多对一的，根本不进行反演。多个外观请求可以导出到同一 RGB，逆只返回搜索所找到并排在首位的那个原像。共享内核中可选的 `hk_guard.inverse` 辅助函数是一个独立的固定参考数学探针，使用有界标量二分；它不属于本路径。

### 20.7 独立的 Stack oracle

`src/stack.py` 为混合的正向/逆向 Stack 实现了第二个、刻意保持分离的逆。它只共享不可变的 D65 上下文——既不共享求解器，也不共享种子，也不共享约化后的坐标系。

值得了解的差异如下：

| | `inverse.py` | `stack.py` |
| --- | --- | --- |
| 搜索坐标 | `arcsinh` RGB，边界 \(\lVert x\rVert_\infty \le 2^{20}\) | `arcsinh(x/0.01)` RGB，裁剪到 `[0, 1024]` |
| 种子 | 先验、目标、零、\(1/4\ldots4\times\)、\(3^3\) 模板、中性原像 | 先验、零、经 \(Y\) 投影的先验、\(1/4\ldots4\times\)、\(3^3\) 模板 |
| 边界处理 | 对称、带符号 | 非负 AP1 立方体 |
| 阻尼 | `1e-3`、`×1/3` / `×10`、`[1e-12, 1e12]` | 相同 |
| 容差与上限 | `2e-10`、128 | `2e-10`、128 |

两个独立搜索为有限求解器配置提供比较证据，并不证明唯一逆。Stack oracle 的 `appearance=True` 模式以已修复、缩放的阶段 3 外观为目标，包含携带的带符号能量，位置在 RGB 立方体投影之前。因此正向→逆向衔接只跳过有损的立方体导出，仍保留 H–K 修复与 Scale。

相邻正向与逆向条目的 Tone 和 Color 设置完全相同时，Stack 通过显式优化消去其非线性计算。其他情况下，正向条目调用 `grade_state`，将已修复、缩放的状态交给外观逆。正向 RGB 导出调用 `release_state(..., guard=True)`，仅执行立方体包含；H–K 修复已完成。空参考 Stack 仍执行原生输入修复。这些规则并不主张全局数学逆。

### 20.8 局限

对给定输入与模型，该搜索是确定性的，其结果不依赖批次形状。它不是对任何命题的证明。具体而言：

- `root` 状态意味着找到了一个原像并在该残差下验证了它；它并不意味着该原像就是用户所意图的那一个，也不意味着不存在更接近的原像。
- Stage 3 中的折叠、带符号扩展以及多对一的立方体投影都可能产生多个有效原像。排序策略在其中做出选择；它并不消解这种歧义。
- 不主张全局收敛。种子集是固定的工程选择，只有从集合之外的种子才可达的原像会被报告为 `approximate` 或被漏掉。
- 128 次迭代上限与阻尼边界是安全限制；因其中任一而终止的候选会按其实际残差报告，而不会被提升为根。

因此，关于该逆的任何精度陈述，都是关于某个特定正向配置、某个特定种子集以及某个实测残差分布的陈述——而不是关于调色这一数学对象的陈述。

