# 保持饱和度的影调曲线

解析参考对非负幅值 \(M=\sqrt{J_A^2+66C}\) 进行重映射，然后将 \(J_A\) 与对色坐标对共同缩放，从而保持色相与带符号的 modCAM16 饱和度。五个中性 nit 地标定义映射；固定影调目标来自参考值与峰值标定。冻结的 1.23.2 产品使用相同的大致曲线构造，但其目标与生效参数规则不同，见下文。

## 构造单调曲线

把每个中性 nit 输入地标转换为 \(J_A/100\)；对中性色而言，它也等于 \(M/100\)。按最小间隔对五个层级排序。把它们的跨度归一化为从 Black 到 Highlights 的结点 \(u_i\)；对应的目标是 \(y_i\)。取最小的正区间斜率 \(m\) 与非负残余抬升 \(r_i\)：

$$
m=\min_i\frac{y_{i+1}-y_i}{u_{i+1}-u_i},\qquad
r_i=y_{i+1}-y_i-m(u_{i+1}-u_i),\qquad w=0.05\,2^{-\mathrm{Fit}}.
$$

每个区间贡献一个平滑的积分 sigmoid 窗：

$$
K_i(t)=\int_0^t\left[
\operatorname{sigmoid}\left(\frac{v-u_i}{w}\right)
-\operatorname{sigmoid}\left(\frac{v-u_{i+1}}{w}\right)\right]dv,
\qquad F(t)=mt+\sum_i r_i\frac{K_i(t)}{K_i(1)}.
$$

由于每个窗的导数与 \(r_i\) 都非负，曲线保持单调。它在 \(t=1\) 处达到 Highlights 目标，越过地标后取线性渐近。中间目标较软。Fit 改变区间过渡的集中程度。

![不同 Fit 设置下的 Tone 曲线](../assets/figures/tone-curves.svg)

<p class="figure-caption">当前参考曲线使用 Shadows 比例 0.015507796089266005。叉号是地标目标；影响平滑重叠，Fit 越高过渡越紧。参考白辅助线位于归一化明度 1。</p>

生效曲线在 Input Black 之上是平滑的。等于或低于该阈值的值映射为零。取消的黑趾处理意味着这个截断不会获得 \(C^2\) 趾；正黑阈值处的平滑性属于另一类边界行为。默认地标走精确恒等分支。复位时只设置 Fit 不会破坏该恒等。

## 通过 H–K 关系保持饱和度

在该固定暗环境下，带符号的 modCAM16 饱和度为 \(s=75C/J_A\)，在 \(J_A\ne0\) 时有定义。正分支的 H–K 关系为：

$$
s=75\frac{C}{J_A},\qquad H^2=J_A^2+66C.
$$

在正分支上，要在保持 \(k=C_1/J_{A,1}\) 的前提下达到目标 \(H_2\)，求解正二次根：

$$
J_{A,2}=\sqrt{H_2^2+(33k)^2}-33k,
\qquad C_2=kJ_{A,2},\qquad h_2=h_1.
$$

实现使用有理化并缩放后的版本，以避免抵消和对极小 \(J_A\) 的除法。其等价形式是用单一增益整体缩放该对坐标，而不重新求 \(J_A\)：

$$
g=\frac{2H_2^2}{\operatorname{hypot}(66C_1,\ 2J_{A,1}H_2)+66C_1},
\qquad J_{A,2}=gJ_{A,1},\qquad C_2=gC_1.
$$

两个表达式在该分支选取同一个根；第二个按构造精确保留 \(C/J_A\)。中性色自然保持 \(C=0\)，黑色取零输出极限。

带符号参考在两种符号下使用同一饱和度保持缩放。令 \(M_1=\sqrt{J_{A,1}^2+66C_1}\)，曲线把它映射为 \(M_2\)，则

$$
g=\frac{2M_2^2}{\operatorname{hypot}(66C_1,\ 2J_{A,1}M_2)+66C_1},\qquad
J_{A,2}=gJ_{A,1},\qquad (a_2,b_2)=g(a_1,b_1),\qquad C_2=gC_1.
$$

输出非黑时增益为正，会保留 \(J_A\) 的符号、色相以及有定义时的 \(C/|J_A|\)。黑色平台使用零增益；分母为零时也输出零。输出坐标用带符号 H–K 映射重新计算：若 \(J_{A,2}\ge0\)，则 \(H_2=M_2\)；若 \(J_{A,2}<0\)，则 \(H_2=2\sqrt{66C_2}-M_2\)。Tone 和后续 Color 影调选择器使用幅值 \(M_2\)，而不是这个带符号的 \(H_2\)。

![保持饱和度与平方 H 两种策略](../assets/figures/tone-saturation.svg)

<p class="figure-caption">此正分支示例从 \(H=100,\ C=20\) 开始。保持 \(C/J_A\) 会令饱和度不变；平方 H 的彩度耦合则让饱和度随映射后的 \(H\) 按比例变化。</p>

Reference Nits 默认 203，它决定 White 的中性明度。Highlights 使用生效峰值，至少为 Reference Nits 的两倍。重映射之后，Color 的影调相关系数使用得到的幅值 \(M_2\)。当前完整解析 Model 将 Grade 白点固定为 D65、Reference Nits 固定为 203；其底层 Tone 辅助函数接受更宽的有效参考值范围。

## 目标与生效配置

五个目标中有四个由参考值与峰值固定：Black 为零，Midtones 为 Reference Nits 的 18%，White 恰为归一化明度 1，Highlights 为有效峰值。Shadows 是 Reference Nits 的一个比例，其取值使下层地标保持感知上的均匀。解析参考使用

$$
y_1=\nu(0.015507796089266005\,R_w)\approx\nu(3.148\ \mathrm{nit}).
$$

1.23.2 的 DCTL 与随包旧绘图模型对同一地标使用 \(0.037153526983R_w\)，即 7.542 nit。在生效参考值与峰值相同时，这是固定目标集中的唯一差异。旧产品还会把生效参考值与峰值四舍五入到整 nit，而解析 Tone 辅助函数采用平滑映射；因此小数或越界输入也可能改变其他目标。当前完整解析 Model 仅接受 D65 / 203 nit。

生效参考值与峰值不是原始输入。参考实现让两者都经过一个有界的平滑映射，因此小数与越界请求都是连续移动的：

$$
R_w=\operatorname{cap}_{1000}\!\left(\operatorname{floor}_{48}(R_{\mathrm{input}})\right),
\qquad
P_w=\operatorname{cap}_{10000}\!\left(\operatorname{floor}_{2R_w}(P_{\mathrm{input}})\right),
$$

其中 \(\operatorname{floor}_\ell\) 与 \(\operatorname{cap}_u\) 是把五次缓入／缓出 \(e(x)=x^3(6-8x+3x^2)\) 作用到距区间边缘的距离上，在边界内一单位处恰为 \(x\)，在边界外恰为边界值，两个衔接点的一阶与二阶导数均连续。早期手册描述的是四舍五入到整 nit；那是 1.23.2 的行为，会在每个半 nit 处产生一个台阶。参考实现请使用平滑形式，并把生效的 \(R_w,P_w\) 当作前向与逆向共享的配置，而不是菜单索引。
