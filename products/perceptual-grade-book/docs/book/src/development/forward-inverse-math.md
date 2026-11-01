# Full forward and inverse math

Implementation: **Perceptual Grade 1.23.2**, 6 October 2026. This handbook maintains the full specification, including p=2 drivers, shared working whites, matrix-owned Stage 1, the fixed native ACEScg/ACES-white LUT boundary, enabled forward/inverse Stack entries, and the installed GPU evaluation profile.
Scope: stages 1, 2, 3, the H–K guard, appearance conversion, signed-color extension, and fallback. Fixed grade parameters and viewing conditions are assumed throughout.

This chapter reconstructs the current forward model and specifies an inverse evaluator for baking an inverse LUT. The inverse is not required to have a slider representation. Equations describe real arithmetic; numerical branches and deployment differences are stated separately. An algebraic reduction followed by scalar or two-variable root solving is called a **semi-analytic inverse** here. It is not a claim of a universal elementary closed-form inverse or of global solver convergence.

The main result is precise: **for a fixed positive reference energy and positive requested lightness, the H–K guard is one-to-one and has a unique inverse obtained from a bounded, strictly monotone scalar equation.** In the full grade, the reference energy belongs to the unknown stage-2 color. Evaluate this guard inverse inside a two-variable inverse of stage 3. Then undo stage 2 and apply the inverse stage-1 matrix.

The full grade can still have multiple preimages. Black clipping, singular matrices, signed extension, fallback selection, finite precision, and creative stage-3 folds require explicit policies. A fixed-reference guard inverse does not by itself establish injectivity of the complete grade.

## 1. Source contract and implementation profiles

The inspected source functions are:

| Source | Relevant functions |
| --- | --- |
| `model/linear.py` | `safe_source_white`, `rgb_to_xyz`, `adaptation`, `references`, `directional_matrix`, `matrices` |
| `model/tone.py` | `viewing`, `response`, `unresponse`, `eccentricity`, `kernel_integral`, `saturation_gain`, `Model.remap`, `Model.attributes`, `Model.core`, `Model.apply` |
| `model/color.py` | `chroma_drivers`, `chroma_crossover`, `Model.stage2_with_ja`, `Model.weights`, `Model.drivers`, `Model.adjustments`, `hue_concentration`, `Model.stage3`, `hk_energy`, `_project_hk_energy`, `Model.decode`, `Model.apply` |
| `model/curves.py` | `integral_jet`, `weights_jet`, `jets`, `coefficients`, `Table`, `BasisTable`, `ToneModel`, `ColorModel` |
| `graph/tone.py`, `graph/color.py`, `graph/curve_tables.py` | Native graph equivalents and coefficient-table evaluation |
| `Perceptual-Grade.dctl` | `pg_model`, `pg_linear`, `pg_stage2_appearance`, `pg_drivers_ja`, `pg_attributes`, `pg_hue_concentration`, `pg_stage3_ja`, `pg_hk_energy`, `pg_project_energy`, `pg_decode_reference`, `pg_core`, `pg_nonlinear_eval` |

The component equations describe the current p=2 classifier and grading model. Section 18 defines the implemented semi-analytic inverse and Stack composition. Section 19 distinguishes the unchanged canonical grading coordinates from the native ACEScg/ACES-white LUT sampling coordinates. The [sampling chapter](../theory/lut.md) explains why this grid was selected; [testing](testing.md#lut-sampling-and-aces-20-display-error) records the experiment and its limits.

When implementing an inverse, select the forward evaluator to invert:

1. **Analytic reference:** evaluate the kernels and coefficient curves below directly in float64.
2. **Deployed Quintic 2048:** use the actual stored coefficient tables, endpoint jets, and evaluation rules in section 14.
3. **Deployed DCTL/native kernel:** preserve its parameter preprocessing, arithmetic precision, validity tests, FMA usage, and bypass decisions when validating candidates.

These profiles share the mathematical design. They are not bitwise interchangeable. In particular, the Python reference is a validation model, not evidence of a completed Resolve/Blender render test. Invert the selected profile and finally validate against the actual renderer if matching that renderer is required.

The DCTL execution order is used below for the complete branch contract. Sections 2–18 express RGB/XYZ boundary conversions in one grading RGB basis for clarity. The Blender scene boundary and per-Grade white are specified in section 19; apply those boundaries to both forward and inverse evaluation. Optional diagnostics, scopes, image statistics, and display rendering are outside this transform.

## 2. Symbols, spaces, and units

Vectors are columns. Products such as division of two cone triples, absolute value of a vector, and scalar response functions on a vector are componentwise unless stated otherwise. All ordinary logarithms are natural logarithms. Trigonometric arguments are radians; stored Hue and Heading controls use degrees.

| Symbol | Definition |
| --- | --- |
| \(x,y\in\mathbb R^3\) | Input and output scene-linear working RGB; negative and above-one values are permitted |
| \(x_1=M_1x\) | Working RGB after stage 1 |
| \(P,P^{-1}\) | Working RGB-to-XYZ and XYZ-to-RGB matrices |
| \(W_s,W_d\) | Source and destination white XYZ, each normalized to \(Y=1\) |
| \(A\) | CAT16 XYZ-to-cone matrix |
| \(Q=\operatorname{diag}(1/(AW_d))AP\) | Working RGB-to-normalized-cone matrix |
| \(n=Qx_1\) | Normalized cone triple before source-specific roundoff zeroing |
| \(q=(H,a,b)\); \(z=a+ib\) | Appearance coordinates; \(z\) is a complex representation of the same real pair |
| \(C=\lvert z\rvert\); \(h=\arg z\) | Actual modCAM16 chroma and hue; hue is irrelevant when \(C=0\) |
| \(J=J_A\) | Achromatic appearance lightness, carried independently of \(H,C\) |
| \(s=75C/J\) | modCAM16 saturation; undefined at exact black |
| \(p_d=2\), \(s_0=35\), \(C_n=2\) | Fixed classifier exponent, saturation midpoint, and absolute-chroma neutral fade scale |
| \(r_s=s_0/75=7/15\) | Ratio converting \(J\) to the classifier boundary |
| \(v_n(C)\), \(\omega(J,C)\) | Neutral visibility and high-saturation membership, defined in section 6.2 |
| \(H=J_{\mathrm{HK}}=\sqrt{J^2+k_{\mathrm{HK}}C}\) | H–K lightness used by the controls |
| \(k_{\mathrm{HK}}=66\) | Fixed chromatic contribution to squared H–K lightness |
| \(q_0,q_2,q_3,q_g\) | Appearance after stage 1, after stage 2, raw stage-3 request, and guarded stage-3 output |
| \(J_i,C_i,z_i\) | The corresponding achromatic lightness, chroma, and complex pair at index \(i\) |
| \(E_r=J_2^2\) | Guard reference energy, fixed by the incoming stage-2 color; called `E0` in source |
| \(E=J_g^2\) | Guard output energy, carried directly into appearance decoding |
| \(X=H_3^2\), \(D=X-66C_3\) | Raw requested squared lightness and raw requested achromatic energy |
| \(U=H_g^2=E+66C_g\) | Guarded squared lightness |
| \(R_w,P_w\) | Effective reference and peak luminances in nits |
| \(\mathcal E(n)\) | Normalized-cone appearance encoding; also returns \(J\) or \(J^2\) directly |
| \(\mathcal D(q,E)\) | Plain appearance decoding to normalized cones using supplied energy; it does **not** apply the guard |
| \(\Phi=\mathcal E\circ Q\) | Working RGB appearance encoding on its valid branch |
| \(T,S,\mathcal R_{E_r}\) | Stage 2, raw stage 3, and fixed-reference H–K guard |

\(H,J,C\) are appearance-coordinate values, not nits or log RGB code values. The grading \(a,b\) have radius \(C\); they are not the logarithmically compressed CAM16-UCS pair.

Carry an internal record such as `Appearance(H, a, b, J)` from encoding through Tone to the classifier. The full paths carry \(J=100(A_c/A_w)^\gamma\), followed by \(J_2=k_TJ_0\). Standalone appearance probes without a carried \(J\) reconstruct \(\sqrt{\max(0,H^2-66C)}\). The H–K guard still derives its reference energy from the stage-2 \(H,C\) in the selected renderer arithmetic; this sampling change does not change that guard policy. In exact arithmetic the two representations agree. Candidate validation must preserve this distinction near cancellation.

## 3. Stage 1: exact matrix construction

### 3.1 Working primaries and white

Define

$$
\operatorname{XYZ}(x_c,y_c,Y)
=Y\left(\frac{x_c}{y_c},1,\frac{1-x_c-y_c}{y_c}\right)^T.
$$

For working primary chromaticities \(p_R,p_G,p_B\), let

$$
P_0=[\operatorname{XYZ}(p_R,1)\;\operatorname{XYZ}(p_G,1)\;\operatorname{XYZ}(p_B,1)],
\qquad s=P_0^{-1}W_d,
\qquad P=P_0\operatorname{diag}(s).
$$

The standalone reference supports these RGB spaces. Blender nodes use the fixed grading basis and selected white in section 19, independently of their scene RGB space:

| Space | Red \(xy\) | Green \(xy\) | Blue \(xy\) | White \(xy\) |
| --- | --- | --- | --- | --- |
| Linear Rec.709 | \((.64,.33)\) | \((.30,.60)\) | \((.15,.06)\) | \((.3127,.3290)\) |
| Linear Rec.2020 | \((.708,.292)\) | \((.170,.797)\) | \((.131,.046)\) | \((.3127,.3290)\) |
| ACEScg | \((.713,.293)\) | \((.165,.830)\) | \((.128,.044)\) | \((.32168,.33767)\) |

For another DCTL space/white selection, use its selected \(P,W_d\) consistently throughout; do not silently substitute Rec.709 or D65.

### 3.2 Source-white preprocessing and adaptation

$$
A=\begin{bmatrix}
.401288&.650173&-.051461\\
-.250268&1.204414&.045854\\
-.002079&.048952&.953127
\end{bmatrix}.
$$

The source projects source-white chromaticity into an admissible polygon. First clamp each coordinate to \([0,.9]\). Require \(y_c\ge.002\) and, for every row \((A_{i1},A_{i2},A_{i3})\),

$$
(A_{i1}-A_{i3})x_c+(A_{i2}-A_{i3})y_c+A_{i3}
\ge .002\sqrt{(A_{i1}-A_{i3})^2+(A_{i2}-A_{i3})^2}.
$$

If the clamped point is outside this convex polygon, project it to the closest point on its boundary in Euclidean \(xy\) distance. The Python model substitutes D65 for nonfinite source coordinates; reject or sanitize nonfinite parameters consistently with the selected host. This is parameter preprocessing, not a per-pixel color operation.

With the resulting \(W_s\),

$$
M_{\mathrm{CAT}}=A^{-1}\operatorname{diag}\left(\frac{AW_d}{AW_s}\right)A.
$$

The Python reset path uses exact identity when source and destination \(xy\) differ by less than \(5\times10^{-8}\) in both coordinates. Preserve effective preprocessed parameters and reset flags when reproducing a host.

### 3.3 Directional controls

Adapt the Rec.709 red and blue primaries from D65 to \(W_d\), convert their XYZ to \(xy\), then take 30% of each displacement from destination-white chromaticity \(w_d\). Call these reference points \(p_r,p_b\).

For each directional control \(i\in\{r,b\}\), with internal Balance \(b_i\) in stops, Spread \(s_i\) in percent and Heading \(\vartheta_i\) in degrees,

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

The DCTL negates the displayed Balance controls before supplying these internal \(b_i\). Do not negate stored internal model values again.

For exposure \(e\) in stops,

$$
\boxed{M_1=2^eP^{-1}M_{\mathrm{dir}}M_{\mathrm{CAT}}P,\qquad x_1=M_1x.}
$$

If all directional controls are zero, the source uses an exact identity directional matrix. Exposure commutes with these matrices.

## 4. Appearance encoding and plain decoding

### 4.1 Viewing constants

The Python reference derives

$$
R_w=\max(48,\min(1000,\lfloor R_{\mathrm{input}}+.5\rfloor)),
$$

$$
P_w=\max(2R_w,\min(10000,\lfloor P_{\mathrm{input}}+.5\rfloor)).
$$

The DCTL peak menu first chooses from 500, 1000, 2000, 4000 nits, promoting an insufficient selection to its supported value satisfying the reference constraint. Treat **effective** \(R_w,P_w\) as configuration shared by forward and inverse; do not reinterpret menu indices as nits.

Define

$$
L_A=.1R_w,\quad k=(5L_A+1)^{-1},
$$

$$
F_L=.2k^4(5L_A)+.1(1-k^4)^2(5L_A)^{1/3},\qquad
\gamma=.943019577159.
$$

The cone response and its inverse are

$$
\rho(n)=\operatorname{sgn}(n)\frac{400(F_L|n|)^{.42}}{27.13+(F_L|n|)^{.42}},
$$

$$
\rho^{-1}(s)=\frac{\operatorname{sgn}(s)}{F_L}
\left(\frac{27.13|s|}{400-|s|}\right)^{1/.42},\qquad |s|<400.
$$

Let \(A_w=3.05\rho(1)\) and \(Q=\operatorname{diag}(1/(AW_d))AP\).

### 4.2 Encode normalized cones

For \(s=\rho(n)\), define

$$
A_c=2s_R+s_G+.05s_B,
$$

$$
a_o=s_R-s_G+(s_B-s_G)/11,\qquad
b_o=(s_R+s_G-2s_B)/9.
$$

If \(s=0\), return exact black \(H=J=C=a=b=0\). Otherwise require \(A_c>0\) and finite results. Then

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

If \(r_o=0\), set \(C=a=b=0\) without computing hue. Also return \(J^2\) directly from \(A_c\). This signed-response encoder can encode valid decoded outputs with negative cone components; do not lift such an output merely to inspect its appearance.

### 4.3 Decode with a supplied achromatic energy

For \(q=(H,a,b)\), \(C=\operatorname{hypot}(a,b)\) and supplied \(E\ge0\), use

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

At \(C=0\), set \(a_o=b_o=0\). Then

$$
\mathcal D(q,E)=\rho^{-1}(s),\qquad x_1=Q^{-1}\mathcal D(q,E).
$$

Source validity requires finite coordinates and output, \(H\ge0\), \(E\ge0\), and \(\max_i|s_i|<399.998\). Exceeding the response limit is an invalid branch, not permission to clip and accept it. The Python model clips \(s\) for safe evaluation but separately rejects that result.

On a regular physical point, \(E=H^2-66C\). After the guard, **use its carried \(E\)**. When encoding an observed RGB output for inversion, compute \(E\) from \(A_c\), not from \(H^2-66C\). Plain decoding here must not silently apply the H–K guard a second time.

## 5. Stage 2: tone and saturation-preserving scaling

### 5.1 Neutral nits and effective landmarks

The neutral-nits coordinate is

$$
\nu(v)=\left(\frac{3.05\rho(\max(v,0)/R_w)}{A_w}\right)^\gamma.
$$

For five input nits values \(v_i\), ordered Black, Shadows, Midtones, White, Highlights, calculate \(j_i=\nu(v_i)\) and enforce sequentially

$$
j_i\leftarrow\max(j_i,j_{i-1}+.001),\quad i=1,\ldots,4.
$$

Define the tone black offset \(\beta_T=j_0\), span \(s_T=j_4-j_0>0\) and \(u_i=(j_i-\beta_T)/s_T\). The target coordinates are

$$
(y_0,y_1,y_2,y_3,y_4)
=\left(0,\nu(.037153526983R_w),\nu(.18R_w),1,\nu(P_w)\right).
$$

Set \(y_0=0,y_3=1\) exactly, as the source does.

### 5.2 Kernel and tone function

For width \(w>0\), define \(\operatorname{sigmoid}(x)=1/(1+e^{-x})\) and

$$
K(t;l,r,w)=\int_0^t\left[\operatorname{sigmoid}\left(\frac{v-l}{w}\right)
-\operatorname{sigmoid}\left(\frac{v-r}{w}\right)\right]dv.
$$

Equivalently, with \(\varphi_w(v)=w\log(1+e^{v/w})\),

$$
K(t;l,r,w)=\varphi_w(t-l)-\varphi_w(-l)-\varphi_w(t-r)+\varphi_w(-r).
$$

Use stable `log1p`, `expm1`, and softplus differences in code. The source uses a narrow-interval branch when \(r-l<.1w\): let \(d=r-l\), \(a=.387298334621\), nodes \(s_j=(l+r)/2+(-a,0,a)_jd\), and weights \((.277777777778,.444444444444,.277777777778)\). Evaluate

$$
K(t)\approx d\sum_j\omega_j\left[
\operatorname{sigmoid}\left(\frac{t-s_j}{w}\right)
-\operatorname{sigmoid}\left(\frac{-s_j}{w}\right)\right].
$$

This numerical branch is part of source matching. Invert the same branch rather than a subtly different ideal integral if exact source reproduction is the objective.

For \(w_T=.05\,2^{-\mathrm{Fit}_T}\), define

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

At \(t=1\), pin the output to \(100y_4\). Intermediate targets are soft constraints, not exact interpolation points. The highlight endpoint is not a clipping ceiling: \(t>1\) is allowed and retains the positive linear tail \(mt\).

If \(\beta_T=0\) and \(\max_i|j_i-y_i|<3\times10^{-7}\), the source takes the identity tone bypass. For an active curve, \(T_H\) is strictly increasing above \(100\beta_T\) and maps all lower lightnesses to zero.

### 5.3 Full stage-2 transformation

For a valid incoming \(q_0\) with \(J_0^2=H_0^2-66C_0\ge0\), let \(H_2=T_H(H_0)\). The positive scale \(k_T\) solves

$$
J_0^2k_T^2+66C_0k_T-H_2^2=0,
$$

so

$$
k_T=\frac{2H_2^2}{\operatorname{hypot}(66C_0,2J_0H_2)+66C_0},
\qquad q_2=(H_2,k_Ta_0,k_Tb_0),\qquad J_2=k_TJ_0.
$$

Both \(J\) and \(C\) scale by \(k_T\), preserving \(75C/J\) and hue. Here \(b_0\) is the incoming opponent coordinate, distinct from the tone black offset \(\beta_T\).

For implementation, the source's scaled quadratic avoids overflow. For generic source \((H,J,C)\) and target lightness \(H_t\), set

$$
r=H_t/H,\quad s=\max(1,r),\quad
u=(J/H)(r/s),\quad v=(33C/H^2)/s,
$$

$$
k=\frac{r/s}{\operatorname{hypot}(u,v)+v}\,r.
$$

Use the zero-output limit if \(H\le0\) or \(H_t\le0\). Exact identity/bypass cases can return the input directly. Standalone appearance probes with no carried \(J\) retain the existing no-fit behavior for \(H^2<66C\). Full paths use valid encoder-derived \(J\) directly and carry its scaled value through Tone; a rounded \(H^2-66C\) no longer controls the classifier or falsely rejects a valid encoded point. Invalid encoding, black clipping and inverse-domain fallback retain their separate checks.

## 6. Stage 3: coefficient curves, contributions, and explicit operations

Throughout this section, \((H,z)=(H_2,z_2)\) is the **original stage-3 input**. No coefficient or driver is recomputed from the rotated, concentrated, gained, or offset color.

### 6.1 Tonal coefficient curves

Let \(H_\star=100y_4\), \(H_i=100y_i\), and

$$
p(v)=6v^5-15v^4+10v^3,\qquad
t=p(\operatorname{clamp}(H/H_\star,0,1)),\qquad
\ell_i=p(H_i/H_\star).
$$

For a family \(f\) with width \(w_f=.05\,2^{-\mathrm{Fit}_f}\), calculate

$$
U_i(H)=\frac{K(t;\ell_i,\ell_{i+1},w_f)}{K(1;\ell_i,\ell_{i+1},w_f)},\qquad i=0,1,2,3.
$$

Apply the source rounding guard sequentially: clamp each value to \([0,1]\) and to no more than the previous value, obtaining \(1\ge U_0\ge U_1\ge U_2\ge U_3\ge0\).

Normal weights and Adaptance weights are respectively

$$
\boldsymbol\beta_f=(1-U_1,U_1-U_2,U_2-U_3,U_3),
$$

$$
\boldsymbol\beta_A=(U_0-U_1,U_1-U_2,U_2-U_3,U_3).
$$

For stored heights \((c_S,c_M,c_W,c_H)\), the coefficient is their dot product with the appropriate weights. These heights are ordered Shadows, Midtones, White, Highlights. Concentration uses the Hue family's Fit and weights. Coefficients hold their last height above Highlights; Adaptance fades to zero at black.

The classifier uses the fixed saturation midpoint below. It has no tonal curve, fixed-Fit interpolation, or peak-dependent calibration. The control coefficients above remain tone dependent.

### 6.2 Drivers and the equivalent 3-by-6 contribution matrix

For the fixed exponent \(p_d=2\), define

$$
\boxed{\omega(J,C)=\frac{C^2}{C^2+r_s^2J^2},\qquad
v_n(C)=\frac{C^2}{C^2+C_n^2},\qquad r_s=\frac{35}{75},\ C_n=2.}
$$

For \(J>0\), \(\omega=s^2/(s^2+s_0^2)\) with \(s=75C/J\). Use the rational expression above at \(J=0\) and never form the possibly infinite saturation ratio in the renderer. The complete drivers are

$$
\boxed{d_\ell=v_n(1-\omega),\qquad d_h=v_n\omega,\qquad
d_a=\frac{a}{\operatorname{hypot}(C,2)},\quad
d_b=\frac{b}{\operatorname{hypot}(C,2)}.}
$$

At \(C=J=0\), define all four drivers as zero. At \(C=0,J>0\), they also vanish. At \(J=0,C>0\), the limiting pair is \((0,v_n)\). The lower/higher weights sum to \(v_n\) and cross at \(s=35\); the shared visibility factor makes their memberships complementary at every input. Tone's common positive scaling \((J,C)\mapsto(kJ,kC)\) leaves \(\omega\) invariant but changes \(v_n\). Thus the classification is saturation invariant; the complete driver values are not exposure invariant.

Evaluate without large squares:

```text
m = max(C, r_s*J)
u = C/m if m > 0 else 0
v = r_s*J/m if m > 0 else 0
D = u*u + v*v
visibility = (C/hypot(C, 2))^2
d_low  = visibility*v*v/D if D > 0 else 0
d_high = visibility*u*u/D if D > 0 else 0
```

Computing both normalized numerators avoids loss of a very small lower weight in `1-high`. For a fixed \(H\), the physically valid chroma domain is \(0\le C\le H^2/66\). The crossover is

$$
C_{50}(H)=r_s\left[\sqrt{H^2+(33r_s)^2}-33r_s\right]
=\frac{r_sH^2}{\operatorname{hypot}(H,33r_s)+33r_s}.
$$

Use the rationalized form (with scaled products) for dark values. The scope's near-neutral statistical selector uses \(C\le C_{50}(H)/4\); that selector does not enter image grading. Neither peak nits nor Fit appears in the classifier.

Let \(L_j(H)\) be Lightness contribution curves in \(H\) units, \(R_j(H)\) Chroma contribution curves in stops, \(g_0\) global chroma gain in stops, \(\theta_0(H)\) the tonal Hue curve in degrees, and \(\theta_\ell,\theta_h\) the global low-/high-chroma Hue controls in degrees. With \(\kappa=\pi/180\),

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

Thus \(H_3=H+\Delta H\) and \(g=e^\sigma>0\). The literal implementation evaluates four drivers plus offsets; this augmented matrix is an equivalent formulation. `pg_attributes` returns \((\Delta H,\theta,\sigma)\), not final \((H,a,b)\).

**Hue-angle calculation belongs to the contribution math; application of hue rotation is a separate operation.** There are no \(d_a,d_b\) terms in the Hue row. Consequently \(\theta\) depends on \(H,C\) but not independently on incoming hue. This is the property used to eliminate hue from the inverse.

### 6.3 Concentration

Let the two Concentration curves form \(v(H)=v_a(H)+iv_b(H)\), and let

$$
\tau=|v|/.6,\qquad
w_c(H,C)=\frac{\tanh\tau}{\tau}\,v(H)\frac{C^2}{C^2+4}.
$$

Use \(\tanh\tau/\tau=1\) at zero. The DCTL uses \(1-\tau^2/3+2\tau^4/15\) for \(\tau<.001\); the Python model uses the continuous hyperbolic-tangent expression. With \(C>0\) and \(u=z/C\),

$$
u_f=\frac{u+w_c}{1+\overline{w_c}u},\qquad z_f=Cu_f.
$$

Since \(|w_c|<.6<1\), denominators on the unit circle cannot vanish. The map preserves \(C\) and orientation. At \(C=0\), set \(z_f=0\); zero Concentration controls use an exact identity fast path.

### 6.4 Gain, hue rotation, and Adaptance

For Adaptance strength \(\alpha\in[0,1]\), define

$$
r_A(C)=.25+\frac{.75}{1+(C/30)^2},\qquad
\eta_A(H,C)=\frac{\max(H,0)}{100}
\frac{\alpha r_A(C)}{1-\alpha+\alpha r_A(C)},
$$

$$
B_A(H,C)=\eta_A(H,C)[A_a(H)+iA_b(H)].
$$

The raw stage-3 output is

$$
\boxed{S(H,z)=\left(H+\Delta H(H,z),\ B_A(H,C)+e^{\sigma(H,z)+i\theta(H,C)}z_f\right).}
$$

Equivalently, the actual Hue operation is \(R_\theta\) on \((a_f,b_f)\), multiplied by scalar \(g\) and followed by the Adaptance offset. The source returns the input unchanged at \(H=0\), and when stage 3 is inactive.

## 7. H–K guard: complete forward math

The guard takes both the raw request \(q_3=S(q_2)\) and its stage-2 reference \(q_2\). Its constants are

$$
k_{\mathrm{HK}}=66,\quad \text{knee}=1,\quad
\text{maximum fractional H lift}=.20,\quad
\lambda=(1+.20)^2-1=.44.
$$

For a finite request with \(H_3\ge0\), define

$$
X=H_3^2,\quad C_3=|z_3|,\quad D=X-66C_3,\quad
E_r=\max(H_2^2-66C_2,0),
$$

$$
\delta=\frac{E_rX}{E_r+X}.
$$

When the denominator is zero set \(\delta=0\). Evaluate the harmonic expression without the potentially overflowing product:

$$
\delta=\frac{\min(E_r,X)}{1+\min(E_r,X)/\max(E_r,X)}
$$

when the maximum is positive.

The repaired achromatic energy is

$$
E=
\begin{cases}
D,&D\ge\delta,\\
\displaystyle\frac{\delta}{(1+4t+10t^2)^{1/4}},\quad t=(\delta-D)/\delta,
&D<\delta,\ \delta>0,\\
0,&D<\delta,\ \delta=0.
\end{cases}
$$

The source evaluates the active branch stably with

$$
v=\frac{\delta}{\delta+\max(\delta-D,0)},\qquad u=1-v,
\qquad
E=\frac{\delta\sqrt v}{\sqrt{\sqrt{v^2+4vu+10u^2}}}.
$$

Allocate this energy repair between lightness lift and chroma reduction:

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

At zero denominators use the explicit zero limit; at \(C_3=0\), leave its zero pair unchanged. If \(E\le D\), return \(q_3\) unchanged. The guard preserves hue wherever chroma is nonzero. It carries \(E\) separately into \(\mathcal D(q_g,E)\).

On the regular domain \(E_r>0,H_3>0,C_3\ge0\), the active-branch clipping operators do not destroy information: \(0<E<\delta<X\), \(0\le G<\min(Z/2,L)\), and

$$
C_g=C_3-(Z-G)/66>0\quad\text{when active}.
$$

Thus the `min` and `max` simply protect numerical boundaries on this domain. Also

$$
H_3\le H_g<1.2H_3,\qquad E+66C_g=H_g^2.
$$

Negative requested \(H_3\), nonfinite requests, and invalid appearance decoding lead to source fallback. Do not treat squaring a negative \(H_3\) as permission to invert it on the positive branch.

## 8. Is the guard invertible? Domain and proof

### 8.1 Positive reference energy: yes, with one scalar root

Hold \(E_r>0\) fixed. Given a guarded output \((H_g,z_g)\) with \(E>0\), define

$$
C_g=|z_g|,\qquad U=E+66C_g=H_g^2.
$$

Prefer forming \(U\) from the carried or directly encoded \(E\) and \(C_g\). If externally supplied redundant fields disagree beyond tolerance, reject the inconsistent record rather than silently altering the color.

If

$$
E\ge\delta(E_r,U)=\frac{E_rU}{E_r+U},
$$

the unique inverse request is the output itself: the guard was inactive.

Otherwise the guard was active. Necessarily \(E<E_r\). For a trial \(X\), define

$$
\delta(X)=\frac{E_rX}{E_r+X},\qquad
t(X)=\frac{\sqrt{10[\delta(X)/E]^4-6}-2}{10},
$$

$$
D(X)=\delta(X)[1-t(X)],\qquad
Z(X)=E-D(X),\qquad L(X)=\lambda X.
$$

The formula for \(t\) is the nonnegative root of

$$
[\delta/E]^4=1+4t+10t^2.
$$

Solve

$$
\boxed{F_E(X)=X+\frac{\lambda X\,Z(X)}{\sqrt{4\lambda^2X^2+Z(X)^2}}=U}
$$

on the guaranteed bracket

$$
\boxed{\max\left(\frac{U}{1+\lambda},\frac{EE_r}{E_r-E}\right)\le X\le U.}
$$

Recover

$$
\boxed{H_3=\sqrt X,\qquad C_3=\frac{X-E+Z(X)}{66},\qquad
z_3=\frac{C_3}{C_g}z_g.}
$$

\(C_g>0\) automatically holds in this active positive-energy branch. A neutral output with \(C_g=0,E>0\) uses the inactive branch.

### 8.2 Why the scalar root is unique

At fixed observed \(E\), differentiating the reversed energy law gives

$$
\frac{dD}{d\delta}=-\frac{15t^2}{1+5t}\le0,\qquad
\frac{d\delta}{dX}=\frac{E_r^2}{(E_r+X)^2}>0.
$$

Therefore

$$
Z'(X)=\frac{15t^2}{1+5t}\frac{E_r^2}{(E_r+X)^2}\ge0.
$$

For \(G(L,Z)=LZ/\sqrt{4L^2+Z^2}\),

$$
\frac{\partial G}{\partial L}=\frac{Z^3}{(4L^2+Z^2)^{3/2}}\ge0,\qquad
\frac{\partial G}{\partial Z}=\frac{4L^3}{(4L^2+Z^2)^{3/2}}\ge0.
$$

Hence

$$
\boxed{F_E'(X)=1+\lambda G_L+G_ZZ'(X)\ge1.}
$$

The residual is strictly increasing. At the lower bracket endpoint it is nonpositive, and at \(X=U\) it is positive for an active repair. Exactly one root exists. Bisection or safeguarded Brent/Newton is appropriate; no multidimensional search is needed for the fixed-reference guard itself.

The inactive and active images cannot overlap: an active result satisfies \(E<\delta(E_r,X)\le\delta(E_r,U)\), whereas an inactive result satisfies the reverse inequality. This also proves the branch test in section 8.1.

For every fixed \(E_r>0\), the guard maps \(H_3>0,C_3\ge0\) bijectively onto \(H_g>0,0\le C_g<H_g^2/66\), retaining hue. In Cartesian coordinates, the neutral case has one zero pair, not multiple distinct colors corresponding to different arbitrary hue labels.

### 8.3 Local conditioning and the knee

At fixed \(X\), on the active branch with \(P_t=1+4t+10t^2\),

$$
\frac{\partial E}{\partial D}=\frac{1+5t}{P_t^{5/4}}>0.
$$

This derivative becomes small for severe compression, so the inverse can amplify error in measured \(E\). Mathematical invertibility does not imply good conditioning after float32 rounding or LUT interpolation.

The Jacobian determinant of \((X,D)\mapsto(U,E)\) is

$$
\det\frac{\partial(U,E)}{\partial(X,D)}
=F_E'(X)\frac{\partial E}{\partial D}>0.
$$

Both branches meet with the source's intended \(C^2\) knee. They are analytic within their open branches, but the entire piecewise guard should not be described as one globally analytic formula across every boundary.

### 8.4 Degenerate domains

| Case | Consequence and implementation policy |
| --- | --- |
| \(E_r>0,H_3>0\) | Unique fixed-reference inverse as above |
| \(H_3=0\) | Every finite chromatic request on this plane is repaired to black; original chroma is unrecoverable |
| \(E_r=0,D>0\) | Guard is inactive; a positive-energy output has the identity preimage |
| \(E_r=0,D\le0\) | Outputs lie on \(E=0\); multiple raw requests can produce the same output |
| Unknown \(E_r\) | Output alone does not determine the raw request; obtain \(E_r\) from the candidate stage-2 color in the combined solve |
| Invalid request or decode | Follow the source's fallback contract, not a fictitious regular guard inverse |

For an explicit zero-reference collision, set \(U=10000\), choose \(X=.9U\), \(G=U-X\), \(L=.44X\) and

$$
Z=\frac{2LG}{\sqrt{L^2-G^2}}.
$$

The two requests \((\sqrt U,U/66,0)\) and \((\sqrt X,(X+Z)/66,0)\) both map to \((100,10000/66,0)\) when \(E_r=0\). Numerically these requests are approximately \((100,151.515151515152,0)\) and \((94.8683298050514,167.681674763361,0)\).

For ordinary nonblack lifted inputs with nonnegative cones, appearance encoding yields \(J_0>0\); a noncollapsed tone result therefore has \(E_r>0\). The degenerate zero-reference case is not the normal working domain, but it must not be silently claimed to be invertible.

## 9. Complete forward execution, including signed inputs and fallback

### 9.1 Regular no-lift branch

Define the guarded stage-3 map

$$
\widetilde S(q_2)=\mathcal R_{E_r(q_2)}(S(q_2)),\qquad E_r(q_2)=J_2^2.
$$

The guard also returns its carried energy \(E\). In exact regular arithmetic,

$$
F(x)=Q^{-1}\mathcal D\bigl(\widetilde S(T(\mathcal E(QM_1x))),E\bigr).
$$

Writing \(\Phi^{-1}\) for plain decoding with the consistent energy gives the compact expression

$$
F=\Phi^{-1}\circ\widetilde S\circ T\circ\Phi\circ M_1.
$$

This expression assumes the valid, no-lift, full-grade branch that reaches the guard/decode path. Exact unchanged-coordinate bypasses can skip that path and must be handled by the complete source logic below.

### 9.2 Roundoff guards and white-offset extension

Let \(v=Px_1\) be XYZ and \(c_w=AW_d\). Before the nonlinear stage, the source evaluates

$$
n=Av/c_w,\qquad
\varepsilon_n=4\times10^{-7}|A|\,|v|/c_w,
$$

then sets \(n_i=0\) where \(|n_i|\le(\varepsilon_n)_i\). This is cancellation-dependent zeroing, not a fixed black threshold. The white cone triple \(c_w\) is distinct from the complex Concentration parameter \(w_c(H,C)\).

Set

$$
\ell_{\mathrm{lift}}=\max(0,-\min_i n_i),\qquad
n_+=n+\ell_{\mathrm{lift}}\mathbf1,
\qquad w_{\mathrm{RGB}}=P^{-1}W_d=Q^{-1}\mathbf1.
$$

The source also zeroes lifted components satisfying

$$
|(n_+)_i|\le4\times10^{-7}(|n_i|+\ell_{\mathrm{lift}}).
$$

In an ordinary normalized working space \(w_{\mathrm{RGB}}=(1,1,1)^T\), but use the configured matrices rather than relying on this shortcut in an inconsistent space.

For mathematical descriptions ignoring these tiny zeroing intervals, define \(\mathcal C_k(n)\) as the normalized-cone core at level \(k\): encode, apply Tone, optionally apply Color, guard and decode. Level 2 includes Color; level 1 omits it. Then

$$
y=Q^{-1}\left[\mathcal C_k(n_+)-\mathcal C_k(\ell_{\mathrm{lift}}\mathbf1)\right]
$$

at the highest valid common level. The Blender compositor unchanged-core shortcut must return the lifted cones \(n_+\), then subtract the neutral core exactly once; version 1.12.0 corrects this shortcut. However, **the exact DCTL core also receives the original XYZ value to preserve identity bypasses**, so its implementation contract is more accurately represented by the following pseudocode in working RGB:

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

Both terms use the **same** level. Level 0 returns the stage-1 result unchanged. Core level 1's guard is inactive on regular valid tone results because its request equals its reference. A completely inactive Tone/Color configuration is an exact nonlinear identity.

The Python model's application helpers express the same design through a stage-2 fallback and normalized-cone cores; the identity/zeroing arithmetic is not byte-for-byte identical to the DCTL in every cancellation case. Use the selected renderer's exact fast paths for final parity tests. No real-valued inverse can recover information deliberately erased by finite-precision zeroing.

## 10. Full nonlinear inverse on the regular branch

### 10.1 Encode the observed output

For a no-lift candidate, calculate

$$
(q_g,J_g)=\mathcal E(Qy),\qquad E=J_g^2.
$$

Use the plain signed-response appearance encoder. Do not apply input-side lifting to \(y\), do not clip negative RGB, and do not apply the guard again. A decoded regular output may contain negative RGB or cone components while still being a valid appearance point.

If encoding is invalid, this does not rule out a signed-extension or fallback preimage. It only rules out this regular full-core interpretation.

### 10.2 Preferred two unknowns

Use \(J_2>0\) and \(C_2>0\) as the two unknowns, rather than independently subtracting to obtain reference energy. For a trial pair,

$$
H_2=\operatorname{hypot}(J_2,\sqrt{66C_2}),\qquad E_r=J_2^2.
$$

This enforces the appearance domain automatically. An optimizer may use \(p=\log J_2\), \(c=\log C_2\); the exact neutral case \(C_2=0\) is handled separately.

Undo the guard with this candidate reference:

$$
(H_3^*,z_3^*)=\mathcal R_{J_2^2}^{-1}(q_g;E).
$$

The star denotes a raw target reconstructed for the current candidate, not an additional grade. It changes as \(J_2\) changes. Never precompute one guard inverse using a neutral reference, the output's energy, or a fixed white energy.

### 10.3 Eliminate original hue analytically

Evaluate the original-input terms \(B_A(H_2,C_2)\), \(\theta(H_2,C_2)\) and \(w_c(H_2,C_2)\). Set

$$
V=z_3^*-B_A(H_2,C_2),\qquad R=|V|,
$$

$$
\eta=e^{-i\theta(H_2,C_2)}\frac{V}{R},\qquad
\boxed{u=\frac{\eta-w_c}{1-\overline{w_c}\eta}.}
$$

For a true preimage with \(C_2>0\), \(R=e^\sigma C_2>0\) and \(|u|=1\). A trial with \(R=0\) cannot be an exact positive-chroma preimage with finite gain. Reject or penalize that trial; a numerical logarithm floor must not turn it into an accepted root.

Construct

$$
q_2=(H_2,C_2\operatorname{Re}u,C_2\operatorname{Im}u).
$$

Recalculate the source drivers at this reconstructed **incoming** point, passing the candidate \(J_2\) directly and obtain \(\Delta H(q_2),\sigma(q_2)\). Solve exactly two real equations:

$$
\boxed{
\begin{aligned}
H_2+\Delta H(q_2)-H_3^*(J_2^2)&=0,\\
\log(R/C_2)-\sigma(q_2)&=0.
\end{aligned}}
$$

This incorporates Concentration, Hue, all Lightness and Chroma contributions, Adaptance, and the reference-dependent guard. The fixed-reference guard contributes a unique inner scalar solve, not another ambiguous inverse branch.

Use a scaled first residual, for example divide it by \(\max(100,H_g)\). The second is already a logarithmic gain residual. This scaling is an optimizer choice, not a change to the exact roots. Use a trust-region method or safeguarded Newton, multiple initial guesses where needed, and continuity from neighboring LUT samples. A single converged local solve is not a proof that all roots have been found.

For derivative-based implementation, the guard's implicit equation \(F_E(X;E_r)-U=0\) gives

$$
\frac{\partial X}{\partial E_r}
=-\frac{\partial F_E/\partial E_r}{\partial F_E/\partial X}.
$$

The denominator is at least one on the active fixed-\(E\) curve. Differentiate the implicit solution, rather than assuming the result of a branching bisection routine has zero derivative. At fixed target \(E,U\), the inactive branch has \(X=U\) and zero derivative with respect to \(E_r\). Within the logarithmic parameterization,

$$
\frac{\partial H_2}{\partial p}=J_2^2/H_2,\quad
\frac{\partial H_2}{\partial c}=33C_2/H_2,\quad
\frac{\partial E_r}{\partial p}=2E_r,\quad
\frac{\partial C_2}{\partial c}=C_2.
$$

For the new classifier's Jacobian, use logarithmic solver coordinates \(\xi=\log J_2\) and \(\chi=\log C_2\) (these are the \(p,c\) coordinates above; neither is the fixed driver exponent \(p_d\)). With \(W=2\omega(1-\omega)\) and \(N=2v_n(1-v_n)\),

$$
\begin{array}{c|cc}
 &\partial_\xi&\partial_\chi\\\hline
\omega&-W&W\\
v_n&0&N\\
d_\ell&v_nW&N(1-\omega)-v_nW\\
d_h&-v_nW&N\omega+v_nW
\end{array}
$$

The remaining coefficient derivatives follow through \(H_2(J_2,C_2)\) using the chain rule. For example, \(\partial_\xi L(H_2)=L'(H_2)J_2^2/H_2\) and \(\partial_\chi L(H_2)=L'(H_2)33C_2/H_2\). Hue still has no independent input-direction driver, so the analytic hue elimination remains valid. Real-valued differentiation of the complex-pair formulas is sufficient; do not assume they are holomorphic functions of the optimizer variables.

### 10.4 Reverse stage 2

Given a recovered regular \(q_2,J_2\), first recover \(H_0=T_H^{-1}(H_2)\). If Tone is inactive, \(H_0=H_2\). Otherwise solve the unique scalar equation

$$
f(t)=H_2/100,\qquad 0\le t\le\frac{H_2}{100m},\qquad
H_0=100(\beta_T+s_Tt).
$$

The bracket follows from \(f(t)\ge mt\) for \(t\ge0\). At an exactly pinned endpoint, retain the same pinning rule. The source curve is not generally invertible through elementary functions; this root or a validated monotone inverse table evaluates \(T_H^{-1}\).

The reverse saturation-preserving scale solves

$$
J_2^2k_-^2+66C_2k_--H_0^2=0,
$$

so

$$
\boxed{k_-=\frac{2H_0^2}{\operatorname{hypot}(66C_2,2J_2H_0)+66C_2}.}
$$

Use the scaled quadratic evaluation from section 5.3 when needed. Then

$$
q_0=(H_0,k_-a_2,k_-b_2),\quad J_0=k_-J_2,\quad
x_1=Q^{-1}\mathcal D(q_0,J_0^2).
$$

Carry \(J_0\) directly; avoid reconstructing its square by subtraction. Validate this decode and the original-input cone domain.

### 10.5 Reverse stage 1 and express the combined inverse

For a nonsingular directional target basis,

$$
M_{\mathrm{CAT}}^{-1}=A^{-1}\operatorname{diag}\left(\frac{AW_s}{AW_d}\right)A,
$$

$$
\boxed{M_1^{-1}=2^{-e}P^{-1}M_{\mathrm{CAT}}^{-1}\mathsf B(\mathsf B')^{-1}P.}
$$

In practice invert or factor the actual effective \(M_1\) once per grade and check its conditioning. Invertible exposure/adaptation does not guarantee invertible directional controls: Spread \(=-100\) can collapse a direction onto white. A singular matrix requires a stated approximate-preimage policy, not an ordinary inverse.

For a selected admissible nonlinear branch \(b\),

$$
\boxed{F_b^{-1}(y)=M_1^{-1}\Phi^{-1}
\left[T^{-1}\left(\widetilde S_b^{-1}(\Phi(y))\right)\right].}
$$

This is the desired nonlinear inverse followed by the stage-1 matrix inverse. The guard is already included in \(\widetilde S_b^{-1}\) through the inner solve above. With inactive guard, its raw target is simply \((H_g,z_g)\) and the same equations reduce to the unguarded stage-3 inverse.

### 10.6 Neutral and black input candidates

Do not use \(\log C_2\) to represent the exact neutral input. At \(C_2=0\), all four contribution drivers vanish, \(H_3=H_2\), and \(z_3=B_A(H_2,0)\). Find any neutral preimage by testing the one-parameter forward curve

$$
H_2\longmapsto\mathcal R_{H_2^2}\bigl(H_2,B_A(H_2,0)\bigr).
$$

For a positive target its possible \(H_2\) values lie in \([H_g/1.2,H_g]\). Solve/search that one-dimensional interval and validate **all** target coordinates, not only lightness. This curve need not supply a preimage for an arbitrary target. An observed neutral can also arise from nonneutral input canceled by Adaptance, so it must not exclude the general two-variable search.

At exact black, the original input is not uniquely recoverable if Tone clips a nonzero interval. A practical default is the valid preimage \(x=0\), labeled as a selected black preimage. Other policy choices require a prior; they cannot be inferred from black output alone.

## 11. Signed-extension and fallback inverse

The no-lift solution is a candidate only if its recovered stage-1 cones satisfy the actual no-lift/roundoff branch and the source selects that level. Negative **RGB** alone does not establish a signed-cone lift; inspect normalized cones.

Ignoring the explicitly documented roundoff zeroing, let \(m_y=Qy\). For a candidate lift \(\ell_{\mathrm{lift}}>0\) and core level \(k\in\{2,1\}\), solve

$$
n_+=\mathcal C_{k,b}^{-1}
\left(m_y+\mathcal C_k(\ell_{\mathrm{lift}}\mathbf1)\right),
$$

subject to

$$
n_+\ge0,\qquad \min_i(n_+)_i=0.
$$

Recover

$$
n=n_+-\ell_{\mathrm{lift}}\mathbf1,\qquad
x=M_1^{-1}Q^{-1}n.
$$

Each full-core inverse is the regular two-variable procedure, with the core target encoded from normalized cones directly. A level-1 core inverse needs only the tone inverse and plain appearance decoding. The remaining lift condition is a scalar outer equation on each continued core inverse branch. Unlike the positive-reference guard equation, this lift equation is **not proven monotone** and can have multiple branches.

For a configured finite input box \(\Omega=[x_{\min},x_{\max}]\), a useful exact linear bound, before roundoff zeroing, is obtained from \(A_1=QM_1\):

$$
n_{j,\min}=\sum_i(A_1)_{ji}
\begin{cases}(x_{\min})_i,&(A_1)_{ji}\ge0,\\(x_{\max})_i,&(A_1)_{ji}<0,
\end{cases}
\qquad
\ell_{\max}=\max(0,-\min_jn_{j,\min}).
$$

Search lifts in \([0,\ell_{\max}]\) with branch continuation or use direct full-forward RGB optimization for the difficult signed cases. Sign-change scanning alone can miss tangential roots. Without a finite configured input domain, do not invent a finite global lift bound.

Always test the linear-only candidate \(x=M_1^{-1}y\): it can be a reset, a per-color unchanged-coordinate bypass, or a level-0 fallback preimage. This also covers exact unchanged branches that skip a guard which would otherwise modify the requested point. For level 1, reconstruct a tone-only candidate. In every case, run the **complete forward evaluator**. If it selects a higher valid level, only accept the candidate if that higher level still reproduces the target; label the actual selected path, not the hypothesized fallback.

These equations explain how to generate candidates for the complete piecewise transform. They do not promise exhaustive enumeration of all signed roots, exact recovery through numerical zeroing, or a globally convergent solver. A practical best-effort implementation must retain a direct full-forward residual minimization path.

## 12. Numerical guard-inverse algorithm

Use the dimensionless unknown \(x_X=X/U\). Its bracket is always contained in \([1/1.44,1]\), avoiding scale-dependent root tolerances.

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

For \(r=\delta/E\ge1\), avoid cancellation in

$$
t=(\sqrt{10r^4-6}-2)/10.
$$

Near \(r=1\), a rationalized expression is

$$
a=\operatorname{expm1}(4\log r),\qquad
t=\frac{a}{\sqrt{4+10a}+2}.
$$

For larger \(r\), use

$$
t=\frac{r^2\sqrt{10-6/r^4}-2}{10}
$$

while monitoring overflow. If \(r^2\) or the recovered chroma exceeds the configured numeric/domain limits, report an ill-conditioned or out-of-domain candidate; do not silently saturate it and label it an exact inverse. Near the knee, \(Z\) is third-order small, so a tiny negative result from subtraction can be rounded to zero within a stated arithmetic tolerance. Re-run the forward guard on the returned request.

Suggested initial float64 controls for ordinary test ranges are a dimensionless root tolerance around \(10^{-12}\) and a residual target around \(10^{-10}\) for the outer solve. These are starting numerical settings, not validated perceptual or GPU tolerances. Make tolerances configurable and scale final RGB acceptance to the target magnitude.

## 13. Candidate selection and best-effort behavior

For each target \(y\), the implementation should return a candidate \(\hat x\), its forward error, selected branch/level, and a status. Suggested statuses are `REGULAR_ROOT`, `NEUTRAL_ROOT`, `SIGNED_ROOT`, `UNCHANGED_ROOT`, `FALLBACK_ROOT`, `APPROXIMATE`, `UNRESOLVED`, and `SINGULAR_STAGE1`.

Use a final acceptance test against the complete chosen-profile forward evaluator, for example

$$
\epsilon_{\mathrm{RGB}}=
\frac{\|F(\hat x)-y\|_\infty}{1+\|y\|_\infty}.
$$

This is a numerical reproduction measure, not a perceptual color difference. A small two-equation residual alone is insufficient: appearance validity, no-lift/signed selection, reference repair, unchanged bypasses, fallback level, and input-domain membership must all agree.

Multiple roots require a policy. One possible default is to prefer roots close to the linear-only inverse \(x_{\mathrm{prior}}=M_1^{-1}y\) using

$$
d_{\mathrm{prior}}(x)=\|\operatorname{asinh}(x/s_d)-\operatorname{asinh}(x_{\mathrm{prior}}/s_d)\|_2^2,
$$

with a documented RGB scale \(s_d>0\) (for example \(s_d=1\) in normalized working RGB), plus continuity with neighboring accepted LUT samples. The prior and continuity weights are inverse-design choices, not part of the original forward source.

If no acceptable exact preimage is found, minimize a specified full-forward error over the configured domain \(\Omega\), optionally regularized by the prior:

$$
\min_{x\in\Omega}
\|W_e(F(x)-y)\|_2^2+\mu\,d_{\mathrm{prior}}(x),\qquad \mu\ge0.
$$

\(W_e\) is an explicitly chosen error-weight matrix; identity is a numerical RGB default. Report the resulting forward residual and label the result `APPROXIMATE`. Searching only the exact two-equation manifold is not a proof of finding the best approximation for an arbitrary RGB error metric.

A source-allowed fold still demonstrates why branch policy is necessary. Set all four high-chroma-to-Chroma heights to \(g_h=-4\) stops, with all other stage-3 controls zero. At fixed \(H\),

$$
C'=C\,2^{g_hd_h(H,C)},\qquad
\left.\frac{dC'}{dC}\right|_H
=2^{g_hd_h}\left[1+g_h\ln2\,C\left.\frac{\partial d_h}{\partial C}\right|_H\right].
$$

Write \(B=C^2+r_s^2(H^2-66C)\). On the regular positive domain,

$$
\left.\frac{\partial\omega}{\partial C}\right|_H
=\frac{r_s^2 C(2H^2-66C)}{B^2},\qquad
v_n'(C)=\frac{8C}{(C^2+4)^2},\qquad
\left.\frac{\partial d_h}{\partial C}\right|_H
=v_n'\omega+v_n\left.\frac{\partial\omega}{\partial C}\right|_H.
$$

The derivative of \(C'\) is negative near the classifier midpoint. At \(H=100\), the p=2 midpoint is \(C_{50}=40.03013072108037\). Two distinct valid inputs with \(h=0\), approximately \(C=12.049497670414462\) and \(C=40.03013072108041\), both produce raw output \((H,a,b)=(100,10.042137411770025,0)\). Both have an inactive guard and valid appearance decoding. This supersedes the old \(C_s\) collision example; no historical driver values are used.

Because the guard reference varies with the input, a fixed-reference bijection alone does not establish injectivity of the full grade. The inactive-guard p=2 collision suffices to disprove a universal unique inverse for all allowed grades.

## 14. Quintic 2048 and scalar inverse tables

### 14.1 Analytic derivative ingredients

For the ordinary kernel, with \(s_l=\operatorname{sigmoid}((t-l)/w)\) and \(s_r=\operatorname{sigmoid}((t-r)/w)\),

$$
K'(t)=s_l-s_r,\qquad
K''(t)=\frac{s_l(1-s_l)-s_r(1-s_r)}{w}.
$$

For the narrow-interval quadrature branch, differentiate the quadrature actually used:

$$
K'(t)\approx\frac{r-l}{w}\sum_j\omega_j s_j^*(1-s_j^*),
$$

$$
K''(t)\approx\frac{r-l}{w^2}\sum_j\omega_j s_j^*(1-s_j^*)(1-2s_j^*),
\quad s_j^*=\operatorname{sigmoid}((t-s_j)/w).
$$

Inside the normalized lightness interval,

$$
p'(x)=30x^2(1-x)^2,\qquad p''(x)=60x(1-x)(1-2x).
$$

For a normalized transition \(K(p(x))/K(1)\), its first two derivatives follow by the chain rule:

$$
U_i'=K_i'(p)p'/K_i(1),\qquad
U_i''=[K_i''(p)(p')^2+K_i'(p)p'']/K_i(1).
$$

Take the same weight differences and height dot products to obtain curve derivatives. These are derivatives with respect to normalized \(x=H/H_\star\); divide by \(H_\star\) or \(H_\star^2\) for derivatives with respect to \(H\).

### 14.2 Existing forward tables

The current source uses 2048 intervals and **2049 shared endpoint jets**. For stage 3, the normalized table coordinate is \(x=\operatorname{clamp}(H/H_\star,0,1)\).

Tone retains its linear tail analytically. It tables only

$$
\mathcal V(\zeta)=\sum_i r_i\frac{K(t;u_i,u_{i+1},w_T)}{K(1;u_i,u_{i+1},w_T)},
\qquad t=\frac{\zeta}{1-\zeta},\qquad \zeta=\frac{t}{1+t},
$$

and evaluates \(f(t)=mt+\mathcal V(\zeta)\). Endpoint \(\zeta=1\) uses the finite residual limit with zero limiting derivatives. Source table generation approximates that endpoint with its prescribed large-\(t\) evaluation. Do not replace this construction with a table that clips the complete tone curve at Highlights.

For \(x_i=i/N\), \(N=2048\), step \(\Delta=1/N\), sample a scalar curve \(g\) and store float32 endpoint triples

$$
(g_i,\ \Delta g_i',\ \Delta^2g_i'').
$$

Let \(d_i=\Delta g_i'\) and \(c_i=\Delta^2g_i''\). In interval \(i\), local coordinate \(u=Nx-i\), construct

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

Evaluate \(\sum_{j=0}^5a_ju^j\) by Horner's rule. Adjacent intervals use the same stored values, slopes, and curvatures.

The deployed basis table stores all four Adaptance weights but only the first three weights of each ordinary family; its fourth ordinary weight is reconstructed as one minus the first three. Together with the Tone residual, this is 14 scalar curves: \(1+4+3+3+3\). The packed texture is \(512\times70\) with 2049 endpoint jets per curve. The obsolete \(\log C_s\) row is removed. The p=2 classifier is evaluated analytically from the carried \(J_2\) and current \(C_2\) in every profile; it is not approximated by Quintic interpolation. Height dot products remain live. Consequently, invert the actual basis-table evaluator when targeting this profile.

The source applies a sufficient monotonicity check to the Tone residual before float32 storage. For derivative power coefficients \(b_j=(j+1)a_{j+1}\), the degree-4 Bernstein coefficients are

$$
B_k=\sum_{j=0}^k b_j\frac{\binom{k}{j}}{\binom{4}{j}},\qquad k=0,\ldots,4.
$$

If a segment has a coefficient below \(-10^{-13}\), it zeroes the shared first and second derivatives at both endpoints, then reconstructs and rechecks affected segments. When implementing this path, also verify monotonicity of the complete **stored/evaluated** tone curve after rounding and transport; the pre-storage check alone is not a bitwise floating-point guarantee.

Texture transport uses power-of-two channel normalization and tiled raw jet data. Reuse the source's texture decoding and scales if matching native output. A mathematically equivalent float64 table is not necessarily the exact GPU table after transport quantization.

### 14.3 A new inverse tone table

A scalar inverse table can be constructed from root-solved endpoint values even if no elementary inverse expression exists. For \(g=T_H^{-1}\),

$$
g'(y)=\frac1{T_H'(g(y))},\qquad
g''(y)=-\frac{T_H''(g(y))}{[T_H'(g(y))]^3}.
$$

Select and record the table's output-lightness domain and normalization, then convert derivatives to that normalized coordinate before constructing endpoint jets. Validate monotonicity, endpoints, extrapolation, and forward reproduction after table quantization. Exclude the black-clipped interval from claims of unique inversion.

**This one-dimensional table can accelerate the tone inverse. It cannot represent the general coupled stage-3 inverse.** Stage 3 plus its input-dependent guard still needs the coupled evaluator or a baked 3D inverse LUT.

## 15. End-to-end inverse-bake algorithm

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

Bake by evaluating this inverse directly against the chosen source model at each **inverse-input** lattice point. This avoids an intermediate forward 3D LUT and its interpolation error. It does not eliminate the final inverse LUT's interpolation error.

Record at least:

- Working primaries/white and all effective grade/viewing parameters.
- Whether the inverse covers stage 1 or expects it to be applied separately.
- Forward evaluator profile, source version, and arithmetic/table precision.
- Input and output shapers, signed-value policy, and domain bounds.
- LUT lattice size, axis ordering, and interpolation method.
- Branch-selection policy, solver tolerances, unresolved/approximate counts, and validation errors.

For a LUT shaper \(\mathcal S_{\mathrm{in}}\) encoding the inverse's input \(y\) and an output shaper \(\mathcal S_{\mathrm{out}}\) encoding its result \(x\), the stored function is

$$
L(u)=\mathcal S_{\mathrm{out}}\left(
F_b^{-1}(\mathcal S_{\mathrm{in}}^{-1}(u))\right).
$$

Specify the actual shapers and their domains; do not assume that \([0,1]\) scene-linear RGB covers HDR or signed colors. Validate both sample nodes and off-grid interpolation points. Forward-after-inverse reproduction is the primary check; inverse-after-forward recovery can legitimately differ when the selected inverse chooses a different valid preimage.

## 16. Verification evidence and implementation acceptance tests

The derivation is exercised by `tests/blender/test_forward_inverse.py` against the current analytic model. The test uses the new rational drivers in the inverse Hue calculation and passes candidate \(J_2\) directly into contribution evaluation. These float64 local-branch checks do not establish global solver convergence or inverse-LUT/GPU accuracy.

| Check | Result |
| --- | --- |
| Guard inverse, 2400 requests; 1603 active | Maximum componentwise normalized recovery error 7.8e-13 |
| Full inverse, 48 RGB inputs with all three stages active; 24 active guards | Maximum absolute RGB recovery error 8.13e-14 |
| Forward reproduction of recovered inputs | Maximum absolute RGB error 1.25e-13 |
| Zero-reference-energy guard collision | Distinct requests agree within 1.42e-14 |

The forward implementation is also covered by independent rational-driver tests, actual graph-expression arithmetic in float32/float64, compiled DCTL acceptance/parity tests, Blender 5.2.2 CPU compositor and Cycles renders, scope/prepared-path checks, and preserved plus separately reviewed p=2 fixture baselines. The historical `docs/engineering/p2-validation-report.md` records that classifier integration; current sampling validation is recorded in [Testing and measurements](testing.md). No Resolve GPU result or completed Buck2 release gate is claimed.

The guard probes used requested \(H_3\) approximately from .01 to 1000, reference ratio \(E_r/H_3^2\) from \(10^{-4}\) to \(10^4\), and chromatic ratio \(66C_3/H_3^2\) from \(10^{-3}\) to \(10^3\). They used the directly carried output energy. Appearance-domain decoding was not required for these standalone guard probes.

### 16.1 Concrete combined fixture

Working space: Linear Rec.709, D65 destination white. All unspecified controls retain their source defaults.

| Setting | Value |
| --- | --- |
| Exposure | \(.4\) stops |
| Source white \(xy\) | \((.34,.35)\) |
| Internal directional Balances, red/blue | \((.12,-.08)\) stops |
| Spreads, red/blue | \((12,-8)\) percent |
| Headings, red/blue | \((7,-9)\) degrees |
| Tone input nits, Black through Highlights | \((0,10,45,260,1250)\) |
| Reference, peak, Tone Fit | \(203,1000,0\) |
| Global chroma gain | \(1.2\) stops |
| Global low-/high-chroma Hue | \((13,-21)\) degrees |
| Adaptance strength | \(.63\) |
| Adaptance/Lightness/Chroma/Hue Fit | \((0,1,0,2)\) |

For each following family/driver, set its four tonal heights to `base * (0.6, 1.1, 0.85, 1.4)`:

| Source stem | Base |
| --- | --- |
| `j_low`, `j_high`, `j_a`, `j_b` | \(-3,-8,2,-1\) respectively |
| `c_low`, `c_high`, `c_a`, `c_b` | \(.08,.15,.05,-.04\) respectively |
| `adaptance_a`, `adaptance_b` | \(1,-1.5\) respectively |
| `hue` | \(7\) |
| `concentration_a`, `concentration_b` | \(.12,-.08\) respectively |

One test vector, rounded for display, is:

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

The guard changes this request substantially, and the output contains negative RGB. Clipping that RGB before inversion destroys the stated round trip. The inverse computed observed \(E\) from the output's encoded achromatic response rather than subtracting \(H_g^2-66C_g\).

The 48-case fixture used the six explicit inputs below plus 42 seeded random inputs. The random generator was NumPy `default_rng(401936)`; the 2400 guard probes consumed its draws first, in the order \(H=10^{\operatorname{uniform}(-2,3)}\), \(E_r/H^2=10^{\operatorname{uniform}(-4,4)}\), \(66C/H^2=10^{\operatorname{uniform}(-3,3)}\), and \(h=\operatorname{uniform}(-\pi,\pi)\). Each draw was an array of length 2400. Then draw a `(42,3)` array uniformly in \([-1.3,.5]\) and raise 10 to those values componentwise. The explicit inputs were:

```text
(1,.05,.03), (.2,.7,.1), (.1,.2,1), (.5,.3,.2), (2,.1,.1), (.3,.3,.3)
```

All tested stage-1 cone triples were positive and the full-level decode was valid. These full-inverse tests did not exercise signed lifting or fallback inversions. They used candidate seeds derived from the observed target, not the known original RGB. The p=2 collision example in section 13 is a separate nonuniqueness check.

### 16.2 Required tests for the engineers' implementation

Before using a production inverse LUT, verify:

0. The p=2 pair, its carried-\(J_A\) arithmetic, \(d_\ell+d_h=v_n\), exact neutral/black behavior, \(s=35\) crossover, derivative formulas, and classifier invariance under positive Tone scaling. Test the visibility fade separately.

1. Exact reset and exposure/matrix-only grades; report singular or poorly conditioned matrices.
2. Pure Tone, pure Hue, pure Concentration, pure gain, pure Adaptance, and mixed grades with varying tonal heights.
3. Both sides of the guard knee, at the knee, and severe active repairs with carried energy.
4. Tiny positive \(J_2\), tiny positive \(C_2\), exact neutral inputs, black, high dynamic range, and valid negative RGB outputs.
5. Zero-reference-energy and zero-requested-lightness degeneracies as explicit nonunique cases.
6. Signed normalized-cone lifts and paired level selection, including valid level-1 and level-0 fallback candidates.
7. Wrong-level candidate detection: evaluate any higher level the source actually selects, require its full output to match, and report the actual path.
8. Source-allowed creative folds and deterministic branch choice across neighboring LUT samples.
9. Actual deployed table/float precision, response-pole rejection, and cancellation zeroing.
10. LUT node and off-grid errors with the exact target shapers/interpolation; no silent RGB clipping.

For a known injective local fixture, check both \(F^{-1}(F(x))\approx x\) and \(F(F^{-1}(y))\approx y\). For a nonunique fixture, require the latter and the documented branch policy, rather than demanding recovery of the unobservable original input.

## 17. Implementation boundary

This specification provides the complete mathematical pipeline, an invertibility proof for the regular fixed-reference H–K guard, a two-variable reduction of its combined stage-3 inverse, and verified numerical examples. The validation does not constitute a production inverse baker, complete enumeration of all preimages, a signed/fallback convergence proof, or target-GPU certification.

The intended production path is: evaluate the selected forward model directly; use the reduced inverse and explicit component inverses to obtain candidates; validate candidates through the complete source branch logic; choose a consistent branch or record an approximate result; then bake and test the final inverse LUT.

## 18. Blender inverse and Stack implementation contract

The CPU implementation is in `model/inverse.py`, `model/transforms.py` and `model/lut.py`; `graph/lut.py` and `graph/stacks.py` integrate it with Blender. It targets the **float64 analytic Python forward model**, including its actual cone-roundoff, lifting, bypass and fallback decisions. From 1.23.0, `model/gpu.py` and `model/gpu_shader.py` provide the installed float32 analytic profile described below. Neither profile targets exact reversal of Direct's Quintic evaluator or of an interpolated forward cube.

### 18.1 Implemented numerical inverse

`model/analytic.py` evaluates the same float64 forward equations as the independent `color.Model` / `tone.Model` references. It shares equal coefficient weights, skips zero terms and evaluates only required stable softplus/fallback branches. The signed-lift neutral offset simplifies to \(q_3=(H_2,\alpha H_2 A_a(H_2)/100,\alpha H_2 A_b(H_2)/100)\): at \(C=0\), all contribution drivers vanish and the Adaptance envelope is \(\alpha H_2/100\). The guard/decoder then share their repeated radius and energy work while retaining branch decisions. It contains no sampled coefficient table or intermediate LUT. The inverse is semi-analytic: explicit component inverses reduce the regular problem, and bounded numerical solves select a usable preimage.

#### Safeguarded scalar inverses

For the active, positive-energy, fixed-reference guard inverse of section 12, use observed energy \(e\), reference energy \(e_0\) and \(u=e+66C_g\). Let \(x=X/u\), where \(X\) is the unknown raw squared lightness. Solve

$$
f(x)=x+G(xu)/u-1=0,\qquad
\max\!\left(\frac1{1.44},\frac{e/u}{1-e/e_0}\right)\le x\le1.
$$

The active branch has \(e<e_0u/(e_0+u)\), so its lower-bound denominator is positive. At a candidate \(X=xu\), define

$$
\delta=\frac{e_0X}{e_0+X},\quad r=\max(1,\delta/e),\quad
 t=\frac{\sqrt{10r^4-6}-2}{10},\quad
Z=\max(0,e-\delta+\delta t),\quad L=.44X,\quad
D=\sqrt{4L^2+Z^2},\quad G=LZ/D.
$$

Use the rationalized expression \(t=(r^4-1)/(\sqrt{10r^4-6}+2)\) near \(r=1\), as in the source. For the active interior,

$$
Z_X=\left(\frac{e_0}{e_0+X}\right)^2
\left(t-1+\frac{2r^2}{\sqrt{10-6/r^4}}\right),
\qquad
f'(x)=1+.44\left(\frac ZD\right)^3
       +\frac12\left(\frac{2L}D\right)^3Z_X.
$$

Start at \(x=1\). Update the sign bracket, then use \(x-f/f'\) if strictly inside it; otherwise use its midpoint. Stop at \(|f|<8\times10^{-14}\), with at most 16 Newton steps. Remaining rows complete 42 bisections on their retained brackets. Reconstruct \(H_3=\sqrt X\) and multiply the observed chromatic vector by \((X-e+Z)/(66C_g)\). This changes the numerical method, not the fixed-reference guard equation. Inactive and degenerate cases keep the branch behavior described earlier.

For Tone, write the normalized remap as

$$
R(t)=m t+\sum_i\frac{v_i}{n_i}K_i(t),\qquad
 t=\max(0,(H_0/100-b)/s_b),
$$

where \(m>0\) is the stored base slope, \(v_i\ge0\) the residual heights, \(n_i=K_i(1)\), \(b\) the normalized input black and \(s_b\) the normalized source span. Away from the narrow-interval quadrature branch,

$$
R'(t)=m+\sum_i\frac{v_i}{n_i}
\left[\sigma((t-l_i)/w)-\sigma((t-r_i)/w)\right],
\qquad \sigma(z)=\frac1{1+e^{-z}}.
$$

For \(r_i-l_i<.1w\), differentiate the same three-node quadrature used by the forward implementation: \(K'_i(t)=(r_i-l_i)\sum_j a_j\sigma_j(1-\sigma_j)/w\), with the source's quadrature nodes/weights. This preserves the implemented forward curve rather than differentiating a different approximation.

Solve \(R(t)=H_2/100\) in \([0,(H_2/100)(1+10^{-12})/m]\). Seed by linear interpolation of the known target/source landmarks, with slope-based extrapolation above the last landmark. Use at most 24 bracketed Newton steps, stopping at \(|R(t)-H_2/100|<2\times10^{-14}(1+H_2/100)\). Unfinished rows use the original 44-step monotone bisection safeguard. Then apply the analytic saturation inverse of section 9. Black uses the explicit zero-output convention.

#### Shared-pool damped Broyden solve

Regular chromatic candidates use section 10's two-unknown reconstruction, including analytic Hue/Concentration undo and the scalar guard inverse. The coordinates are \(v=(\log J_2,\log C_2)\), bounded to \([-18,14]^2\). Neutral and black candidates avoid logarithms of zero chroma. Every resulting RGB candidate is validated through the complete nonlinear forward function \(N\), including lifting, bypass and fallback selection.

The regular two-variable system supplies its analytic branchwise Jacobian \(D=\partial r/\partial v\) at initialization and recovery. The generic full-forward RGB system initializes and recovers \(D\) with one-sided coordinate perturbations \(h=2\times10^{-5}\). Both use the same accepted-step Broyden update. For each unresolved row compute

$$
\left[D^TD+\lambda\bigl(1+\operatorname{tr}(D^TD)\bigr)I\right]p=D^Tr.
$$

Start \(\lambda=10^{-7}\). Limit \(\lVert p\rVert_\infty\) to 1.5 and try \(v-\alpha p\) for \(\alpha\in\{1,1/2,1/8\}\), respecting coordinate bounds. Accept the first finite trial that strictly reduces \(\lVert r\rVert_2^2\). For accepted displacement \(s=v_{new}-v\) and residual change \(z=r_{new}-r\), update

$$
D_{new}=D+\frac{(z-Ds)s^T}{s^Ts}.
$$

Omit the rank-one contribution when \(s^Ts\le10^{-24}\). Accepted steps reduce damping by a factor .2, with floor \(10^{-12}\); rejection increases it by 10, with ceiling \(10^6\). Refresh an approximate Jacobian after rejection and every 12 iterations. A Jacobian already measured at an unchanged point is reused while damping changes. The regular system recovers analytically; the generic RGB system recovers by finite differences. Neither measures a new Jacobian at every accepted step.

For the two-variable system, avoid subtracting nearly equal products when solving the damped normal equation. Define the local Jacobian entries and damping shift by

$$
D=\begin{bmatrix}a&b\\c&d\end{bmatrix},\quad
\delta=ad-bc,\quad \tau=a^2+b^2+c^2+d^2,\quad
\mu=\lambda(1+\tau),\quad \Delta=\delta^2+\mu(\tau+\mu).
$$

For residual \((r_0,r_1)^T\), the step is

$$
p_0=\frac{\delta(dr_0-br_1)+\mu(ar_0+cr_1)}{\Delta},\qquad
p_1=\frac{\delta(ar_1-cr_0)+\mu(br_0+dr_1)}{\Delta}.
$$

These are the same damped normal equations, with a cancellation-safe determinant and numerators at rank one. The three-variable RGB system retains the general matrix solve.

#### Analytic regular Jacobian

Use \(J=J_2>0\), \(C=C_2>0\), \(v=(\xi,\chi)=(\log J,\log C)\), and \(H=\sqrt{J^2+66C}\). All gradients in this subsection are row vectors with respect to \(v\). Then

$$
\nabla H=\left(\frac{J^2}{H},\frac{33C}{H}\right),\qquad
\nabla E_r=(2J^2,0).
$$

The fixed observation's guard inverse returns the requested \((H_3,a_3,b_3)\). On an active guard branch, its scalar equation is \(X+G(X,Z(X,E_r))=U\); observed energy \(e\), repaired energy \(U\), and observed hue are fixed. Use the \(t,r,L\) quantities from the guard-inverse subsection above and write \(D_g=\operatorname{hypot}(2L,Z)\) for its scalar denominator, distinct from the solver Jacobian \(D\). Then

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

Thus \(dH_3/dE_r=X_{E_r}/(2\sqrt X)\). If the observed chromatic vector is \(z_g=a_g+ib_g\), its requested counterpart is \(z_3=z_g(X-e+Z)/(66C_g)\), so

$$
\frac{dz_3}{dE_r}=\frac{z_g}{66C_g}
\left(X_{E_r}+\frac{dZ}{dE_r}\right).
$$

On the inactive branch both derivatives with respect to reference energy are zero. Multiply these scalar derivatives by \(\nabla E_r\) to obtain their solver-coordinate gradients. This differentiates the reference-dependent guard jointly with stage 3; it does not freeze the unknown stage-2 energy.

Differentiate each coefficient curve at its actual clipped smoother position. For \(s=\operatorname{clip}(H/H_{\rm high},0,1)\) and \(t=s^3(6s^2-15s+10)\),

$$
\frac{dt}{dH}=\frac{30s^2(s-1)^2}{H_{\rm high}}.
$$

Multiply the implemented kernel derivative by this factor and the kernel normalization. The kernel's narrow-interval quadrature derivative is the same one defined for Tone above. Clipped kernel values have zero derivative outside their open interval; a cumulative minimum carries the derivative of the selected operand. Multiply the resulting basis derivative by the stored coefficient heights. Families with identical Fit share their kernel work; zero coefficient families need no curve evaluation.

For the chromatic reconstruction, define \(o\) as the Adaptance complex offset, \(z=z_3-o\), \(R=|z|>0\), \(\eta=e^{-i\theta}z/R\), and \(w\) as the bounded Concentration disk parameter including its neutral fade. The analytically reconstructed input direction is \(u=(\eta-w)/(1-\overline w\eta)\). Its gradients are

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

Differentiate the p=2 lower/higher-chroma pair using section 10's classifier gradients. For \(n=C/\operatorname{hypot}(C,2)\), \(\nabla n=(0,n(1-n^2))\), so the direction drivers have gradients \(\nabla(n\operatorname{Re}u)\) and \(\nabla(n\operatorname{Im}u)\). If \(h(H)\) is the scalar Hue curve and \(h_\ell,h_h\) the global low/high Hue controls in degrees, then

$$
\nabla\theta=\frac\pi{180}\left[h'(H)\nabla H+h_\ell\nabla d_\ell+h_h\nabla d_h\right].
$$

For the bounded Concentration controls \(v_c(H)\in\mathbb R^2\), let \(t=\lVert v_c\rVert/.6\), \(f(t)=\tanh(t)/t\), and \(\beta=f(t)v_c\). Its tone derivative is

$$
\beta'(H)=f(t)v_c'(H)+k(t)v_c\,[v_c\cdot v_c'(H)],\qquad
k(t)=\frac{1-\tanh^2(t)-f(t)}{(.6t)^2}.
$$

At small \(t\), evaluate \(k(t)=[-2/3+8t^2/15-34t^4/105]/.6^2\), with the continuous limit \(f(0)=1\). Represent the two components of \(\beta\) as a complex number and set \(w=\beta n^2\); then

$$
\nabla w=n^2\beta'(H)\nabla H+\beta(0,2n^2(1-n^2)).
$$

For Adaptance, use \(s=(C/30)^2\), \(r_A=.25+.75/(1+s)\), \(b_A=1-\alpha+\alpha r_A\), and \(\omega_A=\alpha r_A/b_A\), where \(\alpha\in[0,1]\) is the fixed strength. Then

$$
\partial_\chi r_A=-\frac{1.5s}{(1+s)^2},\qquad
\partial_\chi\omega_A=\frac{\alpha(1-\alpha)\partial_\chi r_A}{b_A^2}.
$$

If \(a_A(H)\) is the complex Adaptance curve, \(o=a_AH\omega_A/100\), so

$$
\nabla o=\frac{\omega_A}{100}[Ha_A'(H)+a_A(H)]\nabla H
       +\frac{H a_A(H)}{100}(0,\partial_\chi\omega_A).
$$

These provide \(\nabla z=\nabla z_3-\nabla o\) for the complex reconstruction above. The complex radius floor used by the numerical implementation carries zero radius derivative below its floor and never establishes an accepted root by itself.

Let \(d\) be the resulting four drivers, \(j(H)\) and \(c(H)\) the lightness and log2-chroma coefficients, \(g\) the global log2-chroma gain, and \(S=\max(100,H_g)\) the fixed observation scale. The two residuals and Jacobian rows are

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

Every trial still computes the actual residual, and every recovered RGB candidate still passes the complete forward reproduction check. The analytic derivative changes solver cost, not the accepted forward function, iteration limits, or diagnostic tolerance.

Rows with \(\lVert r\rVert_\infty\le2\times10^{-11}\) leave the active pool. The regular reduction allows 24 iterations. Signed/fallback and other unresolved targets use full-forward RGB refinement, allowing 30 iterations per seed. For target \(y\), its coordinates represent

$$
\rho=\max(10^{-7},\lVert y\rVert_\infty),\qquad
x_N=\operatorname{clip}(\rho v,-2^{20},2^{20}),\qquad
r(v)=\frac{N(x_N)-y}{1+\lVert y\rVert_\infty}.
$$

The search coordinates are additionally bounded to \([-10^{14},10^{14}]^3\). Target-relative **linear** coordinates replace the former asinh solver coordinates; the LUT's nonnegative log1p *address shaper* is a separate sampling choice. Every refinement trial still evaluates the complete float64 forward equations.

#### Candidate choice and diagnostics

1. Construct the regular candidate, clip it to the search domain and measure its complete-forward residual \(\epsilon_N\) below. Prefer it immediately if \(\epsilon_N\le2\times10^{-10}\).
2. For unresolved/nonfinite results, test the unchanged target as an identity/fallback candidate. Keep it only if its finite residual is smaller.
3. Refine the current best candidate for rows still above \(2\times10^{-10}\). Retain a finite result only if it improves the measured residual.
4. For remaining rows, solve the target and half-target seeds together in one combined pool. Consider the target-seeded result first. Consider the half-target result only if that row is still above \(2\times10^{-10}\). Keep only improvements.

There is no elapsed-time cutoff, previous-bake warm start, neighbor regularizer or coarse sampled initializer. The policy is deterministic for fixed numerical inputs/environment; it is not an exhaustive root search, proof of a global minimum or continuity guarantee across folds. It may select a different valid preimage than version 1.14.0. The solver policy is included in the LUT signature.

The stored diagnostic tolerance is deliberately looser than the internal stopping thresholds:

$$
\epsilon_N=\frac{\lVert N(\hat x_N)-y\rVert_\infty}
                   {1+\lVert y\rVert_\infty}\le2\times10^{-8}.
$$

Samples above it remain best-effort samples and are counted explicitly; the worst residual is stored on the packed LUT image. Diagnostics count returned vertices, not seed attempts. Float32 storage and between-vertex interpolation errors are measured separately. Exact identity bypasses retain signed/HDR inputs unchanged.

#### Installed GPU evaluation profile

The runtime compiles Python-contained source with Blender's
`GPUShaderCreateInfo`. One compute invocation evaluates a lattice vertex through
the complete enabled sequence. The forward function uses the same analytic
Tone, modCAM16, p=2 \(C/J_A\) drivers, 3×6 contributions, concentration,
Hue, Adaptance, H–K guard, signed-lift and fallback equations, evaluated in
float32. There is no intermediate Quintic curve or Grade LUT.

For each inverse entry, the regular \((\log J_2,\log C_2)\) solve uses measured
finite-difference Jacobians with damped Broyden updates, at most 24 iterations,
and the explicit two-variable normal step above. Fixed-reference H–K and Tone
inverses use safeguarded scalar Newton policies scaled for float32. The complete
forward RGB recovery tries the regular candidate, identity and half-target
seeds, each with at most 24 three-variable iterations. The CPU's analytic
regular Jacobian and stricter stopping thresholds are not claimed for this profile.

Version 1.23.2 evaluates the complete two- and three-dimensional Broyden update
on vector columns. With \(D\), accepted displacement \(s\), and residual change
\(z\) as defined above, let \(D_{:,i}\) denote column \(i\). Then

$$
(D_{new})_{:,i}=D_{:,i}+\frac{((z-Ds)s_i)}{s^Ts},\qquad
i=0,\ldots,n-1,\quad n\in\{2,3\}.
$$

The GPU omits the contribution when \(s^Ts\le10^{-20}\). Each column's
multiplication, division and addition is evaluated on a `vec2` or `vec3`, then
the updated matrix is constructed from those columns. This avoids both the
undeclared `outerProduct` builtin and matrix/scalar division rejected by the
reported Blender Metal compiler. It preserves multiplication before division,
the mathematical update and the existing GPU stopping policy.

Let \(y\) be one inverse entry's target, \(\hat x\) its selected candidate,
and \(F_{32}\) that entry's complete float32 forward function. Define

$$
s_{\mathrm G}(y)=\max(10^{-12},\lVert y\rVert_\infty),\qquad
e_{\mathrm G}=\frac{\lVert F_{32}(\hat x)-y\rVert_\infty}{s_{\mathrm G}(y)},
\qquad \tau_{\mathrm G}=3\times10^{-6}.
$$

The relative scale preserves small dark adjustments. Using
\(1+\lVert y\rVert_\infty\) with this float32 threshold would allow large relative
errors near black. A returned candidate is audited against the complete
forward operation. The device records a vertex bit if RGB recovery was used,
and another if any inverse entry remains unresolved/nonfinite. Its final
unresolved audit conservatively uses the RGB Euclidean norm against
\(\tau_{\mathrm G}s_{\mathrm G}\), so it can flag a vertex that passes the
infinity-norm stopping test.

For every flagged vertex, the host reevaluates **the entire Stack** through the
float64 CPU path, including all matrices and Bradford connections, then stores
that replacement. Flagged vertices from bounded GPU batches share one CPU
recovery pool per preview/refinement phase. Unrepaired values are private and
cannot publish. It does not refine or verify every unflagged vertex on the
CPU. Remaining nonfinite output aborts the GPU bake and selects CPU recovery.
Singular inverse matrices use the CPU pseudoinverse path directly.

The cube's policy identifier is `analytic-f32-relative3e-6-audited-v1`.
Diagnostics record GPU sample/search/flag counts, repaired CPU vertices and
repair time. CPU approximation/residual fields describe only repaired vertices;
they do not establish the CPU \(2\times10^{-8}\) diagnostic tolerance for the
unflagged GPU grid. LUT interpolation and extrapolation remain separate errors.

Input/output AP1 coordinate conversions and final storage are host operations;
each GPU dispatch uploads one numerical parameter snapshot and reads back a
bounded vertex batch. A 33³/65³ pair still evaluates exactly 274,625 vertices,
reusing common float32 values bit for bit. If a published matching GPU preview
must finish on CPU, refinement preserves those common values and computes only
the remaining vertices. CPU-completed cubes retain these preview audits under
`gpu_preview_*` fields; their CPU residual counts cover only CPU-evaluated work.
See [runtime scheduling](architecture.md#gpu-context-scheduling-and-recovery)
and [validation](testing.md#installed-gpu-baking-1230).

### 18.2 Ordinary Grade direction and matrix placement

For Grade \(g\), let \(M_g\) be Stage 1 and \(N_g\) its full analytic nonlinear transform. Define
$$
F_g(x)=N_g(M_gx),\qquad
I_g(y)=M_g^\dagger\,\widehat{N_g^{-1}}(y).
$$
Here \(M_g^\dagger=M_g^{-1}\) when its condition number is at most \(10^{12}\); otherwise it is the Moore–Penrose pseudoinverse with relative singular-value cutoff \(10^{-12}\). The latter is explicitly approximate. It need not minimize the full grade residual because the nonlinear candidate may not lie in the range of the singular matrix.

In canonical grading coordinates, an ordinary Grade node always applies its Grade forward. Its Baked LUT path evaluates \(\widehat{\mathcal N}_g(M_gx)\): Stage 1 stays exact outside the nonlinear cube. Its node-local Render Method selects Baked LUT or Direct. An inverse is applied by a Stack entry, including a one-entry Stack, and its complete matrix inverse is baked into that Stack’s cube. Shared Grade data stores neither direction nor render method. Section 19.5 specifies the native ACEScg coordinate changes.

### 18.3 Stack composition and one final cube

A Stack owns an ordered list of shared Grade references, enabled states and directions. Empty and bypassed entries are omitted. Here \(i=1,\ldots,m\) enumerates the enabled, populated entries in order, and \(d_i\) selects \(F_{g_i}\) or \(I_{g_i}\). The list is local to its node; Grade IDs remain shared. Define

$$
T_i=\begin{cases}F_{g_i},&d_i=\mathrm{forward},\\I_{g_i},&d_i=\mathrm{inverse},\end{cases}
\qquad \mathcal S_{\mathrm{stack}}=T_m\circ\cdots\circ T_1.
$$

Here \(T_i\) denotes a whole Grade entry, distinct from the Stage 2 operator \(T\) defined earlier. Let \(B_{\mathrm L}\) convert canonical grading RGB to native ACEScg/ACES white; section 19.1 defines its matrix. For the fixed nonnegative log1p axis \(a_j\), \(0\le j<65\), bake

$$
V_{ijk}=\operatorname{float32}\!\left[
 B_{\mathrm L}\,\mathcal S_{\mathrm{stack}}\!\left(B_{\mathrm L}^{-1}[a_i,a_j,a_k]^T\right)
\right].
$$

Every \(T_i\), including its matrix, runs in float64 on each CPU sample or through the analytic float32 GPU profile above, with flagged whole-Stack CPU recovery. No intermediate 3D LUT or Quintic approximation is sampled. No additional clamp is placed between entries. Empty and bypassed rows are skipped; a sequence with no enabled Grades is identity. Runtime evaluates one physical-linear-ACEScg tetrahedral interpolation of \(V\); alpha bypasses the transform.

The grid is \(65^3\) over \([0,128]^3\), with zero at address 0 and 64 positive cells per component. Its plain log1p constant is \(k=0.01\). [Direct and sampled evaluation](../theory/lut.md) defines the address curve and its inverse. Negative inputs extrapolate the first physical cell; values above 128 extrapolate the last. Stored output values remain signed linear ACEScg/ACES white. The CPU/Shader interpolant uses the equivalent vertex-difference form. Compositor storage encodes one base plane and three forward-axis difference planes independently with RGBE; it reads one base and three ordered edges and accumulates the physical fractions with fused multiply-adds. This is one LUT representation, not four chained transforms. Reducing the number of interpolations does not establish a universal precision improvement: the composed function may have sharper curvature or selected-inverse discontinuities.

Stack signatures include the sampling basis, grid bounds, shape constants, solver policy/version and the ordered enabled entries with their directions, Grade whites and all three stages’ settings. Skipped entries do not contribute. Blender scene space affects only the outer matrices. Names and editor focus are excluded. Stack diagnostics validate complete inverse entries, including their matrices, and count singular matrices separately.

### 18.4 Runtime and acceptance evidence

Stack editing first evaluates a nested \(33^3\) grid. Let \(a_i\), \(0\le i\le64\), be the final axis above. Define the preview axis \(b_j=a_{2j}\), \(0\le j\le32\), and preview vertex array \(U\). For the same immutable Stack parameters,

$$
U_{ijk}=\operatorname{float32}\!\left[
 B_{\mathrm L}\,\mathcal S_{\mathrm{stack}}\!\left(B_{\mathrm L}^{-1}[b_i,b_j,b_k]^T\right)
\right],\qquad V_{2i,2j,2k}=U_{ijk}.
$$

Define the remaining index set

$$
\mathcal R=\{0,\ldots,64\}^3\setminus
\{(2i,2j,2k):0\le i,j,k\le32\}.
$$

Only vertices in \(\mathcal R\) are analytically evaluated during refinement. Thus \(33^3=35{,}937\) samples produce the preview and \(|\mathcal R|=65^3-33^3=238{,}688\) additional samples complete the final cube. Shared float32 samples are retained bit for bit; final vertices are never interpolated from the preview. Inverse diagnostics accumulate over these disjoint sets, so every final vertex is counted once per inverse entry. Preview interpolation uses the physical endpoints \(b_j,b_{j+1}\); final interpolation uses \(a_i,a_{i+1}\). Both use four tetrahedral reads and identical scene adapters, signed extrapolation and alpha handling.

The preview has 32 positive cells per component, with no negative sample branch. Both levels use a 1024-pixel atlas width; the Shader raw-vertex atlas heights are 36 and 269 respectively. The Compositor single-image base/edge atlas has four planes, with heights 141 and 1073. It independently packs the base and forward differences to avoid half-float subtraction error, while retaining four reads per lookup. Packed images carry their grid size and a resolution-specific signature; native address kernels and scope caches use the installed resolution. Changing resolution does not compose two LUTs.

A first preview becomes eligible after 40 ms, without restarting that delay for each mouse event. A single CPU worker receives immutable NumPy data and never accesses Blender objects; GPU dispatches use main-thread drawing contexts and timer publication. During continuous edits, an in-flight preview may finish and be installed for its captured parameters while newer edits coalesce into one latest successor. A preview cannot replace an already installed final cube for the current parameters. Refinement starts after 300 ms without an edit and only for a matching completed preview. CPU inverse phases use one shared unresolved pool, preserving compaction across the entire phase instead of independent small batches. GPU vertices independently complete their bounded solves, with flagged whole-Stack CPU recovery. Forward evaluation retains bounded blocks for the remaining vertices.

Edits cancel obsolete final work at cooperative checkpoints. Removal and teardown cancel queued jobs. Arbitrary stale jobs and every stale final cube are rejected; only the tracked in-flight preview may temporarily lag controls during continuous edits. Both scopes and native output read the same installed cube, and refresh on preview and final publication. Before the first preview, a clearly marked identity path is used. Render preparation and normal save finish the latest **65³** bake synchronously, even with a preview installed or an older preview in flight; pending foreground GPU work finishes on CPU. Bake errors are surfaced. The extension uses Python, Blender's bundled NumPy and Blender's own runtime shader compiler, with no external precompiled package or native extension binary.

`test_progressive_lut.py` verifies nested coordinates, exact shared-vertex reuse, disjoint work counts, cancellation and inverse diagnostics. The Stack editing suite covers native 33³/65³ output, scope invalidation, continuous-edit coalescing, node removal and final-quality synchronization. `benchmark_progressive.py` measures first-preview and total numerical latency against independent 65³ bakes.

`test_inverse_math.py` verifies the vector guard against the independent scalar derivation, complete signed/positive forward reproduction, matrix order, deterministic evaluation and singular-matrix diagnostics. `test_inverse_solver.py` checks scalar Newton safeguards, tone derivatives, optimized/reference forward parity, secant solving, whole-lattice scheduling, cancellation and progress. `test_grade_stack.py` exercises actual Blender ownership, shared edits, stale completion rejection, cooperative worker cancellation, native Shader/Compositor lookup and alpha, animation, save/load, disabled-extension appearance and forward-only ordinary nodes. `test_shared_grade_undo.py` exercises actual undo/redo of entry direction and bypass while ordinary Render Method stays independent. `evaluate_inverse_precision.py` measures off-grid errors for the stored IMG_* fixtures and synthetic signed/HDR inputs. `benchmark_inverse.py` measures new numerical bakes without using completed LUT caches. The precision and performance reports accompany the implementation. Existing independent derivation tests remain in place. `test_stack_editing.py` runs the added RNA, compact UI, diagram gesture, installed-LUT scope and native persistence regressions through the Blender fixture runner.


## 19. Shared Grade white, authoritative matrices and fixed LUT coordinates

This section is the Blender 1.21.0 contract. There is no older-project migration or slider-import path. The DCTL retains its existing Destination White behavior and does not perform automatic stored-matrix conversion. Its CAT16-adapted red/blue anchors are unchanged.

### 19.1 Additional symbols and the Bradford transform

All matrices act on column vectors. Whites are normalized to \(Y=1\).

| Symbol | Meaning |
| --- | --- |
| \(W_0\) | D65, \(xy=(.3127,.3290)\), the fixed canonical grading white |
| \(W_{\mathrm L}\) | ACES white, \(xy=(.32168,.33767)\), the fixed LUT boundary white |
| \(W_g\) | Chosen working white of shared Grade \(g\); defaults to \(W_0\) |
| \(W_r\) | Recorded reference white of the stored Stage 1 coefficients |
| \(B\) | Bradford XYZ-to-cone matrix, distinct from CAT16 \(A\) in section 2 |
| \(C_{a\to b}\) | Bradford adaptation from white \(W_a\) to \(W_b\) |
| \(P_0\) | Standard linear Rec.709/D65 RGB-to-XYZ matrix from section 3.1 |
| \(P_g=C_{0\to g}P_0\) | XYZ interpretation of canonical grading RGB for Grade \(g\) |
| \(P_{\mathrm L}\) | Native ACEScg/AP1 RGB-to-XYZ matrix normalized to ACES white |
| \(B_{\mathrm L}=P_{\mathrm L}^{-1}C_{0\to\mathrm L}P_0\) | Canonical grading RGB → LUT RGB, including D65-to-ACES Bradford adaptation |
| \(M_{g,r}\) | Authoritative stored Stage 1 XYZ matrix, including exposure, recorded at \(W_r\) |
| \(M_{g}=C_{r\to g}M_{g,r}C_{r\to g}^{-1}\) | Stage 1 XYZ matrix expressed at the selected Grade white |
| \(L_g=P_g^{-1}M_gP_g\) | Stage 1 in fixed grading RGB coordinates |
| \(A_s\) | Blender-native conversion from current scene RGB to linear Rec.709/D65 |
| \(N_g\) | Complete Stage 2+3 evaluator in fixed RGB coordinates, using \(P_g,W_g\) |

The Bradford matrix is

$$
B=\begin{bmatrix}
 .8951& .2664&-.1614\\
-.7502&1.7135& .0367\\
 .0389&-.0685&1.0296
\end{bmatrix},\qquad
C_{a\to b}=B^{-1}\operatorname{diag}\!\left(\frac{BW_b}{BW_a}\right)B.
$$

For the supported positive-cone white presets, this is invertible and

$$
C_{b\to a}=C_{a\to b}^{-1},\qquad
C_{b\to c}C_{a\to b}=C_{a\to c}.
$$

Presets are D65, daylight D60 \((.32161671,.33761992)\), ACES \((.32168,.33767)\), D50 \((.34567,.35850)\), D55 \((.33242,.34743)\), D75 \((.29903,.31488)\), DCI \((.314,.351)\) and equal-energy E \((1/3,1/3)\). Blender offers no custom working-white xy. The preset is shared with the Grade; direction and enabled state belong to Stack entries; Render Method belongs to ordinary Grade nodes.

On Blender's main thread, sample `mathutils.Color.from_scene_linear_to_rec709_linear()` on the three unit RGB vectors to obtain the columns of \(A_s\). This uses the active Blender/OCIO gamut and white conversion. The implementation uses \(A_s^{-1}\) from that same matrix, rather than combining independently rounded forward and reverse probes. For native Linear Rec.709, \(A_s=I\). Cache invalidation covers file reloads and working-space changes. Workers receive numerical snapshots, never Blender API objects.

### 19.2 Complete forward and inverse at the scene boundary

Interpret the component equations of sections 3–9 using \(P=P_g\) and \(W_d=W_g\). All CAT16, H–K, tone, chroma-driver, Hue/Concentration, signed-lift and fallback rules remain in force. The complete analytic forward grade is

$$
\boxed{F_{g,s}(x_s)=A_s^{-1}\,N_g\!\left(L_g A_s x_s\right).}
$$

The selected semi-analytic inverse is

$$
\boxed{I_{g,s}(y_s)=A_s^{-1}\,L_g^\dagger\,
       \widehat{N_g^{-1}}\!\left(A_s y_s\right).}
$$

The pseudoinverse threshold and candidate policy are those in section 18. Pseudoinverse minimum norm is defined in the fixed grading RGB basis, not separately in each Blender scene gamut. Negative RGB is retained through both scene matrices.

For a conceptual XYZ nonlinear function \(\mathcal N_g\) at \(W_g\),

$$
N_g(r)=P_g^{-1}\mathcal N_g(P_g r),\qquad
P_gN_g(L_gr)=\mathcal N_g(M_gP_gr).
$$

Thus the RGB implementation is exactly the requested adaptation into the Grade white, complete grading there, and adaptation back. The nonlinear model's `to_cone` and `from_cone` already include \(P_g\) and \(P_g^{-1}\); do not add those adaptations a second time.

If \(x_t=T_{s\to t}x_s\) denotes the same color in another scene space, the consistent scene-coordinate transform is \(T_{s\to t}=A_t^{-1}A_s\). Then

$$
F_{g,t}(T_{s\to t}x_s)=T_{s\to t}F_{g,s}(x_s).
$$

The same relation holds for the selected inverse and for the fixed sampled LUT, apart from floating-point evaluation. The Grade matrix, its chosen white, Tone/Color values and LUT signature are not changed by a Blender scene-space switch. Input colors must themselves be converted; identical numerical triples in different RGB spaces are not equivalent colors.

### 19.3 White changes and matrix storage

For an explicit Grade-white change \(W_a\to W_b\), retain the correction by

$$
\boxed{M_b=C_{a\to b}M_aC_{a\to b}^{-1}.}
$$

Because \(P_b=C_{a\to b}P_a\), \(L_b=L_a\) in exact arithmetic. Stage 1 therefore retains its color action even though its source white, exposure and directional editing readouts may change. Tone/Color parameters remain numerically unchanged. In general \(N_b\ne N_a\): changing the appearance context does not preserve the nonlinear creative operation.

The Grade stores nine double-precision XYZ coefficients and a recorded white, not nine authoritative slider values. For an unanimated matrix, changing white stores the conjugated matrix and updates its recorded white. When matrix animation exists, keep the coefficients and their recorded white: evaluate \(C_{r\to g}M_{g,r}(t)C_{r\to g}^{-1}\) at every frame. This is a constant coordinate conversion around the evaluated matrix, so it covers arbitrary interpolated keys, NLA and drivers without rewriting animation curves. New edits are converted back into the recorded basis before storage.

Linear auto-keying records all nine matrix coefficients. Computed slider readouts have no independent animation channels. Matrix interpolation is not generally interpolation in exposure stops, source xy or heading angles. A duplicate Grade copies its active Action independently as before. A full Linear reset stores identity, including when the editing readout is approximate.

### 19.4 Derive Stage 1 controls from a regular matrix

Let \(w=\operatorname{XYZ}(W_g,1)\) and \(M=M_g\). The directional matrix fixes \(w\), and the creative CAT16 matrix maps its source white to \(w\). Therefore, for the regular representable case,

$$
u=M^{-1}w,\qquad k=1/u_Y,\qquad e=\log_2 k,
\qquad W_s=u/u_Y,\qquad (x_s,y_s)=\operatorname{xy}(u).
$$

Construct the creative CAT16 matrix \(K=\operatorname{CAT16}(W_s\to w)\) exactly as in section 3.2. Then

$$
D=k^{-1}MK^{-1},\qquad Dw=w.
$$

For the unchanged adapted Rec.709 anchor \(p_i\), define \(v_i=D\operatorname{XYZ}(p_i,1)\), \(q_i=\operatorname{xy}(v_i)\), \(a_i=p_i-\operatorname{xy}(w)\) and \(b_i=q_i-\operatorname{xy}(w)\). The internal balance, spread and heading are

$$
\beta_i=\log_2(v_{i,Y}),\qquad
s_i=100\left(\frac{\lVert b_i\rVert}{\lVert a_i\rVert}-1\right),\qquad
\theta_i=\frac{180}{\pi}\operatorname{atan2}
(a_{i,x}b_{i,y}-a_{i,y}b_{i,x},a_i\cdot b_i).
$$

The UI displays \(-\beta_i\) as Balance. This decomposition requires valid positive luminances and an admissible source white; the target-y construction guard must also be inactive for exact reconstruction.

For a singular matrix the implementation uses the least-squares preimage closest to white,

$$
u=w+M^+(w-Mw),
$$

and produces finite editing values where possible. Invalid gains/xy use the documented finite neutral fallback in `linear.decompose`. Such values are only an editing view. Compute the normalized matrix reconstruction residual

$$
\epsilon_{\mathrm{UI}}=
\frac{\lVert M-f(p)\rVert_{\max}}{1+\lVert M\rVert_{\max}},
$$

where \(f\) constructs an XYZ matrix from the derived controls \(p\). Show an approximate-readout notice if \(\epsilon_{\mathrm{UI}}>2\times10^{-8}\). Never overwrite \(M\) by \(f(p)\) during reads, refreshes, scope evaluation or scene changes. A normal control edit \(p\to p'\) preserves an unrepresentable remainder through

$$
M'=M+f(p')-f(p).
$$

An exposure-only edit instead uses \(M'=2^{e'-e}M\), preserving all existing matrix structure. Cancelling a handle gesture restores the exact matrix snapshot. Source-white edits use the existing admissible-domain projection; converted readouts may lie beyond normal slider soft ranges without clamping the stored matrix.

### 19.5 LUT boundaries and mixed-white Stacks

Every extension cube has **fixed native linear ACEScg/ACES-white input and output coordinates**. Canonical grading RGB remains linear Rec.709 interpreted through \(P_g\); changing the sampling basis must not change the Grade model, anchors, white, matrix or controls. ACES white at the LUT boundary is not a physical display assumption and does not restrict the whites of Grades inside a Stack.

Let \(f\) be any complete nonlinear function expressed in canonical grading coordinates. Define its LUT-coordinate representation and stored vertex array by

$$
f_b(z)=B_{\mathrm L}f(B_{\mathrm L}^{-1}z),\qquad
V^f_{ijk}=\operatorname{float32}\!\left(f_b([a_i,a_j,a_k]^T)\right).
$$

Define \(\mathcal C_b[f](z)\) as physical-linear-RGB tetrahedral interpolation of \(V^f\) at the native ACEScg input \(z\). The subscript \(b\) identifies the sampling basis; it is unrelated to the appearance-coordinate scalar \(b\). Thus \(B_{\mathrm L}^{-1}\mathcal C_b[f](B_{\mathrm L}r)\) approximates \(f(r)\) without changing its meaning.

Ordinary Grade nodes evaluate the forward LUT path:

$$
\boxed{
 y_s=A_s^{-1}B_{\mathrm L}^{-1}\,
 \mathcal C_b[N_g](B_{\mathrm L}L_g A_s x_s)
}
$$

Stage 1 stays outside an ordinary cube. The native LUT branch combines \(B_{\mathrm L}L_gA_s\) into one input matrix and \(A_s^{-1}B_{\mathrm L}^{-1}\) into one output matrix. Direct separately uses \(L_gA_s\) and \(A_s^{-1}\). Ordinary Baked LUT nodes may use their current Direct evaluation while baking. Stack image output and scopes use the installed complete Stack LUT while a replacement is pending.

For enabled, populated Stack entry \(i\), use the canonical-coordinate forward map \(G_i(r)=N_i(L_ir)\) or selected inverse \(G_i(r)=L_i^\dagger\widehat{N_i^{-1}}(r)\) according to Direction. Then

$$
\mathcal S_{\mathrm{stack}}=G_n\circ\cdots\circ G_1,\qquad
\boxed{
 y_s=A_s^{-1}B_{\mathrm L}^{-1}\,
 \mathcal C_b[\mathcal S_{\mathrm{stack}}](B_{\mathrm L}A_s x_s).
}
$$

The analytic bake includes every entry's Stage 1, nonlinear operations and inverse selection, with no intermediate LUT. Adjacent Grade XYZ contexts connect by

$$
P_{i+1}P_i^{-1}
=C_{0\to i+1}C_{0\to i}^{-1}
=C_{i\to i+1},
$$

which is Bradford between their selected whites. This connection is implicit in successive coordinate-aware evaluators. An extra CAT between their canonical RGB outputs would double-adapt the sequence.

The cube shape is independent of Blender's working space. A scene-space change updates \(A_s\) and its composed native matrices, reusing the cube. A Grade-white change modifies the baked function and invalidates affected ordinary and Stack cubes. The selected white also participates in scope/model cache keys. Alpha bypasses these RGB operations.

D65 is the chosen internal grading default. These scene-linear nodes remain before the view transform. D65 does not make processing display-referred, select an encoding or override an ACES creative white. A saved native graph retains its last evaluated matrices; changing scene space with the extension disabled does not update them.

### 19.6 Sampling choice and implementation evidence

The production grid uses native ACEScg/ACES white, bounds \([0,128]\), 64 positive cells and plain log1p \(k=0.01\). There is no negative sample branch, but original negative inputs and signed outputs are retained. Physical-cell extrapolation and a numerically stable vertex-difference interpolant are defined in [Direct and sampled evaluation](../theory/lut.md). This candidate wins the display-linear/peak-nits objective among the fully validated +128 finalists; the encoded-RGB objective selects a different curve. The [domain study](lut-domain-study.md) records both objectives, experimental inputs and measured limitations.

The production validation uses `test_lut_study.py`, `test_cube_math.py`, `test_cube_native.py`, `test_lut_grid_regression.py`, `test_working_white.py` and native render fixtures. `evaluate_lut_sampling.py --production` measures the actual Baker/Cube path through all four requested ACES 2.0 outputs on every stored IMG_* pixel. Solver residuals, basis covariance, native graph transport and off-grid interpolation errors remain distinct measurements.

### 19.7 Stack inspection and editing

For Stack input \(x_s\), evaluate the installed cube and its actual native matrices to obtain \(y_s\). Let \(\Phi_g(r)\) be the selected Grade’s appearance measurement, including its white and reference settings but applying no creative grading. The Tone scopes measure \(J_{\mathrm{in}}=[\Phi_g(A_sx_s)]_J/100\) and \(J_{\mathrm{out}}=[\Phi_g(A_sy_s)]_J/100\). The displayed tone curve and editable handles belong to Grade \(g\). Stage 3 image statistics analyze Stack output in that same selected context. A pending bake does not run an analytic sampled image preview. Scopes refresh when the matching installed cube changes. These diagnostics do not change the rendered transform.
