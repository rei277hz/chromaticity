// The compute shader follows the ACES fixed-function ordering in the shared
// modcam16-color-core implementation. Table values come from its checked-in
// OCIO-derived payload, also used by the WASM fallback. Independent
// PyOpenColorIO tests remain the numerical authority.

type Gpu = any;
export type ImageSourceMode = "display-linear-xyz-d65" | "scene-reference-aces";

const WORKGROUP = 8;
const gpuBufferUsage = () => (globalThis as any).GPUBufferUsage ?? {
  MAP_READ: 0x0001, COPY_SRC: 0x0004, COPY_DST: 0x0008,
  UNIFORM: 0x0040, STORAGE: 0x0080,
};
const gpuMapMode = () => (globalThis as any).GPUMapMode ?? { READ: 0x0001 };

const shader = /* wgsl */ `
struct Settings { width: u32, height: u32, profile: u32, j: f32, mode: u32, reference_white_encoded_as_linear_203: u32, fullRec2020: u32, source_mode: u32 }
@group(0) @binding(0) var<uniform> settings: Settings;
@group(0) @binding(1) var<storage, read> data: array<f32>;
@group(0) @binding(2) var<storage, read_write> output: array<vec4<f32>>;
@group(0) @binding(3) var<storage, read> input_pixels: array<vec4<f32>>;

const PI: f32 = 3.141592653589793;
const J_PEAK: f32 = 217.2768649129496;
const HDR203_DIFFUSE_WHITE_SCALE: f32 = 2.03;
const AUTHORING_REC2020_PEAK: f32 = 10.0 / HDR203_DIFFUSE_WHITE_SCALE;
const SOURCE_EPS: f32 = 1.0e-7;
// Shared with the CPU/WASM path; R=1 contains Rec.2020 blue.
const FITTED_RADIUS_K: f32 = 5.977038579617132;
const FITTED_RADIUS_D: f32 = 3.557365336640551;
const PROFILE_STRIDE: u32 = 56u;
const TABLES_OFFSET: u32 = 224u;
const TABLE_STRIDE: u32 = 1815u;

fn clamp3(v: vec3<f32>, lo: f32, hi: f32) -> vec3<f32> { return clamp(v, vec3<f32>(lo), vec3<f32>(hi)); }
fn matData(base: u32, v: vec3<f32>) -> vec3<f32> {
  return vec3<f32>(
    data[base] * v.x + data[base + 1u] * v.y + data[base + 2u] * v.z,
    data[base + 3u] * v.x + data[base + 4u] * v.y + data[base + 5u] * v.z,
    data[base + 6u] * v.x + data[base + 7u] * v.y + data[base + 8u] * v.z,
  );
}
fn signPow(v: f32, exponent: f32) -> f32 { return sign(v) * pow(abs(v), exponent); }
fn ap0ToLms(v: vec3<f32>) -> vec3<f32> {
  return vec3<f32>(.445181042*v.x + .34964928*v.y - .00112973212*v.z, .123734146*v.x + .613643706*v.y + .0563228019*v.z, .0117007261*v.x + .0280607939*v.y + .753939033*v.z);
}
fn acescgToAp0(v: vec3<f32>) -> vec3<f32> {
  return vec3<f32>(.6954522413574518*v.x + .14067869647029416*v.y + .16386906217225403*v.z, .04479456337203763*v.x + .8596711184564216*v.y + .09553431817154036*v.z, -.005525882558113544*v.x + .004025210305978659*v.y + 1.001500672252135*v.z);
}
fn ap0ToAcescg(v: vec3<f32>) -> vec3<f32> {
  return vec3<f32>(1.4514393161456653*v.x - .23651074689374019*v.y - .21492856925192524*v.z, -.07655377339602043*v.x + 1.1762296998335731*v.y - .0996759264375522*v.z, .008316148425697719*v.x - .006032449791021028*v.y + .9977163013653233*v.z);
}
fn xyzToRec2020(v: vec3<f32>) -> vec3<f32> {
  return vec3<f32>(1.716651187971268*v.x - .3556707837763925*v.y - .2533662813736599*v.z, -.666684351832489*v.x + 1.6164812366349388*v.y + .0157685458139111*v.z, .0176398574453108*v.x - .0427706132578085*v.y + .9421031212354739*v.z);
}
fn xyzToP3(v: vec3<f32>) -> vec3<f32> {
  return vec3<f32>(2.4934969119*v.x - .9313836179*v.y - .4027107845*v.z,
    -.8294889696*v.x + 1.7626640603*v.y + .0236246858*v.z,
    .0358458302*v.x - .0761723893*v.y + .9568845240*v.z);
}
fn p(base: u32, index: u32) -> f32 { return data[base + index]; }
fn tableBase(base: u32) -> u32 { return TABLES_OFFSET + u32(p(base, 55u)) * TABLE_STRIDE; }
fn reachSample(hue: f32, base: u32) -> f32 {
  let h = hue - floor(hue / 360.0) * 360.0;
  let i = u32(floor(h)) + 1u;
  let start = tableBase(base);
  let a = data[start + min(i, 362u)];
  let b = data[start + min(i + 1u, 362u)];
  return mix(a, b, fract(h));
}
fn cuspSample(hue: f32, base: u32) -> vec3<f32> {
  let h = hue - floor(hue / 360.0) * 360.0;
  let start = tableBase(base);
  let cusp = start + 363u;
  let hues = cusp + 1089u;
  var probe = i32(floor(h)) + 1;
  var lo = max(probe - 1, 0);
  var hi = min(probe + 2, 361);
  loop {
    if (lo + 1 >= hi) { break; }
    if (h > data[hues + u32(probe)]) { lo = probe; } else { hi = probe; }
    probe = (lo + hi) / 2;
  }
  let lower = u32(hi - 1);
  let upper = u32(hi);
  let t = clamp((h - data[hues + lower]) / (data[hues + upper] - data[hues + lower]), 0.0, 1.0);
  let a = vec3<f32>(data[cusp + lower*3u], data[cusp + lower*3u + 1u], data[cusp + lower*3u + 2u]);
  let b = vec3<f32>(data[cusp + upper*3u], data[cusp + upper*3u + 1u], data[cusp + upper*3u + 2u]);
  return mix(a, b, t);
}
fn rgbToJmh(rgb: vec3<f32>, lmsBase: u32, parameterized: bool) -> vec3<f32> {
  let lms = select(ap0ToLms(rgb), matData(lmsBase + 9u, rgb), parameterized);
  let q = vec3<f32>(signPow(lms.x,.42)/(27.1299992+pow(abs(lms.x),.42)), signPow(lms.y,.42)/(27.1299992+pow(abs(lms.y),.42)), signPow(lms.z,.42)/(27.1299992+pow(abs(lms.z),.42)));
  let a = 20.25881*q.x + 10.129405*q.y + .506470263*q.z;
  let b = 15480.0*q.x - 16887.2734*q.y + 1407.27271*q.z;
  let c = 1720.0*q.x + 1720.0*q.y - 3440.0*q.z;
  if (a <= 0.0) { return vec3<f32>(0.0); }
  var h = degrees(atan2(c, b));
  if (h < 0.0) { h += 360.0; }
  return vec3<f32>(100.0*pow(a,1.13705599), length(vec2<f32>(b,c)), h);
}
fn solveJ(j: f32, m: f32, focus: f32, gain: f32, jMax: f32) -> f32 {
  let ms = m / gain;
  let a = ms / focus;
  if (j < focus) { let b = 1.0-ms; let c = -j; let r = sqrt(max(b*b - 4.0*a*c, 0.0)); return -2.0*c/(b+r); }
  let b = -(1.0+ms+jMax*a); let c = jMax*ms+j; let r = sqrt(max(b*b-4.0*a*c,0.0)); return -2.0*c/(b-r);
}
fn focusGain(j: f32, cuspJ: f32, jMax: f32) -> f32 { let threshold=.7*cuspJ+.3*jMax; if (j > threshold) { let g=log((jMax-threshold)/max(.0001,jMax-j))/log(10.0); return g*g+1.0; } return 1.0; }
fn gamutBoundary(c: vec3<f32>, gammaTop: f32, gammaBottom: f32, jSource: f32, jCusp: f32, slope: f32, jMax: f32) -> f32 {
  let lower=jCusp*pow(jSource/jCusp,gammaBottom)/(c.x/c.y-slope); let upper=c.y*(jMax-jCusp)*pow((jMax-jSource)/(jMax-jCusp),gammaTop)/(slope*c.y+jMax-c.x); let s=.12*c.y; let h=max(s-abs(lower-upper),0.0)/s; return min(lower,upper)-h*h*h*s/6.0;
}
fn remapInverse(m: f32, boundary: f32, reach: f32) -> f32 { let ratio=boundary/reach; let proportion=max(ratio,.75); let threshold=proportion*boundary; if (proportion >= 1.0 || m <= threshold) { return m; } let scale=(reach-threshold)/((reach-threshold)/(boundary-threshold)-1.0); let nd=(m-threshold)/scale; if(nd >= 1.0) { return threshold+scale; } return threshold+scale*(-nd/(nd-1.0)); }
fn gamutInverse(jmh: vec3<f32>, jx: f32, base: u32) -> vec3<f32> {
  let j=jmh.x; let m=jmh.y; let h=jmh.z; let jMax=p(base,36u); if (m <= 0.0 || j > jMax) { return vec3<f32>(j,0.0,h); }
  let cusp=cuspSample(h,base); let fw=min(1.0,1.3-cusp.x/jMax); let focus=mix(cusp.x,p(base,39u),fw); let gain=p(base,40u)*focusGain(jx,cusp.x,jMax); let js=solveJ(j,m,focus,gain,jMax); let sb=select(jMax-js,js,js<focus); let slope=sb*(js-focus)/(focus*gain); let jc=solveJ(cusp.x,cusp.y,focus,gain,jMax); let boundary=gamutBoundary(cusp,cusp.z,p(base,41u),js,jc,slope,jMax); if(boundary<=0.0){return vec3<f32>(j,0.0,h);} let reach=jMax*pow(js/jMax,.879464149)/(jMax/reachSample(h,base)-slope); let remapped=remapInverse(m,boundary,reach); return vec3<f32>(js+remapped*slope,remapped,h);
}
fn gamutInverseOcio(jmh: vec3<f32>, base: u32) -> vec3<f32> { let cusp=cuspSample(jmh.z,base); let threshold=.7*cusp.x+.3*p(base,36u); if(jmh.x<=threshold){return gamutInverse(jmh,jmh.x,base);} let first=gamutInverse(jmh,jmh.x,base); return gamutInverse(jmh,first.x,base); }
fn toneInverse(j: f32, base: u32) -> f32 { let a=.0323680267*pow(abs(j)*.00999999978,.879464149); let y=pow(27.1299992*a/(1.0-a),2.38095238); let yi=y/.7937005721; let z=clamp(yi,0.0,p(base,42u)); let ht=.5*(z+sqrt(max(z*(.16+z),0.0))); let yo=p(base,43u)/(pow(p(base,44u)/ht,.8695652354)-1.0); let fly=pow(abs(yo),.42); return sign(j)*100.0*pow(fly/(27.1299992+fly)*30.8946857,1.13705599); }
fn toeInverse(x:f32, limit:f32, k1In:f32, k2In:f32)->f32 { let k2=max(k2In,.001); let k1=sqrt(k1In*k1In+k2*k2); let k3=(limit+k1)/(limit+k2); if(x>limit){return x;} return (x*x+k1*x)/(k3*(x+k2)); }
fn chromaInverse(jmh: vec3<f32>, base: u32) -> vec3<f32> {
  let jts=jmh.x; let mcp=jmh.y; let h=jmh.z; let j=toneInverse(jts,base); if(mcp==0.0){return vec3<f32>(j,0.0,h);} let r=radians(h); let co=cos(r); let si=sin(r); let mn=co*p(base,45u)+(2.0*co*co-1.0)*p(base,46u)+(4.0*co*co*co-3.0*co)*p(base,47u)+si*p(base,48u)+(2.0*co*si)*p(base,49u)+(3.0*si-4.0*si*si*si)*p(base,50u)+p(base,51u); let nj=jts/p(base,36u); let snj=max(1.0-nj,0.0); let limit=pow(nj,.879464149)*reachSample(h,base)/mn; var m=toeInverse(mcp/mn,limit,nj*p(base,52u),snj); m=limit-toeInverse(limit-m,limit-.001,snj*p(base,53u),sqrt(nj*nj+p(base,54u))); m*=mn*pow(jts/max(j,1e-6),-.879464149); return vec3<f32>(j,m,h);
}
fn jmhToAp0(jmh: vec3<f32>) -> vec3<f32> { let r=radians(jmh.z); let a=pow(jmh.x*.00999999978,.879464149); let b=jmh.y*cos(r); let c=jmh.y*sin(r); let ra=vec3<f32>(.0323680267*a+2.07657631e-5*b+1.32606210e-5*c,.0323680267*a-4.10250432e-5*b-1.20174373e-5*c,.0323680267*a-1.01296409e-5*b-2.90076074e-4*c); let lim=min(abs(ra),vec3<f32>(.99000001)); let lms=sign(ra)*pow(27.1299992*lim/(1.0-lim),vec3<f32>(2.38095236)); return vec3<f32>(2.66705441*lms.x-1.52505875*lms.y+.117925502*lms.z,-.535811961*lms.x+1.94158089*lms.y-.145848125*lms.z,-.0214489009*lms.x-.0485954471*lms.y+1.32996535*lms.z); }
fn inverseAces(xyz: vec3<f32>, base: u32) -> vec3<f32> { let rgb=clamp3(matData(base,xyz),0.0,p(base,37u)); let jmh=chromaInverse(gamutInverseOcio(rgbToJmh(rgb,base,true),base),base); return clamp3(ap0ToAcescg(jmhToAp0(jmh)),0.0,p(base,38u)); }
fn toneForward(j:f32,base:u32)->f32 { let a=.0323680267*pow(abs(j)*.00999999978,.879464149); let y=pow(27.1299992*a/(1.0-a),2.38095238); let f=p(base,44u)*pow(y/(y+p(base,43u)),1.14999998); let yts=max(f*f/(f+.0399999991),0.0); let fly=pow(.7937005721*yts,.42); return sign(j)*100.0*pow(fly/(27.1299992+fly)*30.8946857,1.13705599); }
fn toeForward(x:f32,limit:f32,k1In:f32,k2In:f32)->f32 { let k2=max(k2In,.001); let k1=sqrt(k1In*k1In+k2*k2); let k3=(limit+k1)/(limit+k2); if(x>limit){return x;} let value=k3*x-k1; return .5*(value+sqrt(value*value+4.0*k2*k3*x)); }
fn chromaForward(jmh:vec3<f32>,base:u32)->vec3<f32> { let j=jmh.x; let m=jmh.y; let h=jmh.z; let jts=toneForward(j,base); if(m==0.0||j==0.0){return vec3<f32>(jts,0.0,h);} let r=radians(h);let co=cos(r);let si=sin(r);let mn=co*p(base,45u)+(2.0*co*co-1.0)*p(base,46u)+(4.0*co*co*co-3.0*co)*p(base,47u)+si*p(base,48u)+(2.0*co*si)*p(base,49u)+(3.0*si-4.0*si*si*si)*p(base,50u)+p(base,51u);let nj=jts/p(base,36u);let snj=max(1.0-nj,0.0);let limit=pow(nj,.879464149)*reachSample(h,base)/mn;var mcp=m*pow(jts/j,.879464149)/mn;mcp=limit-toeForward(limit-mcp,limit-.001,snj*p(base,53u),sqrt(nj*nj+p(base,54u)));mcp=toeForward(mcp,limit,nj*p(base,52u),snj);return vec3<f32>(jts,mcp*mn,h); }
fn remapForward(m:f32,boundary:f32,reach:f32)->f32 {let ratio=boundary/reach;let proportion=max(ratio,.75);let threshold=proportion*boundary;if(proportion>=1.0||m<=threshold){return m;}let scale=(reach-threshold)/((reach-threshold)/(boundary-threshold)-1.0);let nd=(m-threshold)/scale;return threshold+scale*nd/(1.0+nd);}
fn gamutForward(jmh:vec3<f32>,jx:f32,reachValue:f32,base:u32)->vec3<f32>{let j=jmh.x;let m=jmh.y;let h=jmh.z;let jMax=p(base,36u);if(m<=0.0||j>jMax){return vec3<f32>(j,0.0,h);}let cusp=cuspSample(h,base);let fw=min(1.0,1.3-cusp.x/jMax);let focus=mix(cusp.x,p(base,39u),fw);let gain=p(base,40u)*focusGain(jx,cusp.x,jMax);let js=solveJ(j,m,focus,gain,jMax);let sb=select(jMax-js,js,js<focus);let slope=sb*(js-focus)/(focus*gain);let jc=solveJ(cusp.x,cusp.y,focus,gain,jMax);let boundary=gamutBoundary(cusp,cusp.z,p(base,41u),js,jc,slope,jMax);if(boundary<=0.0){return vec3<f32>(j,0.0,h);}let reach=jMax*pow(js/jMax,.879464149)/(jMax/reachValue-slope);let remapped=remapForward(m,boundary,reach);return vec3<f32>(js+remapped*slope,remapped,h);}
fn jmhToTarget(jmh:vec3<f32>,base:u32)->vec3<f32>{let r=radians(jmh.z);let a=pow(jmh.x*.00999999978,.879464149);let b=jmh.y*cos(r);let c=jmh.y*sin(r);let ra=vec3<f32>(.0323680267*a+2.07657631e-5*b+1.32606210e-5*c,.0323680267*a-4.10250432e-5*b-1.20174373e-5*c,.0323680267*a-1.01296409e-5*b-2.90076074e-4*c);let lim=min(abs(ra),vec3<f32>(.99000001));let lms=sign(ra)*pow(27.1299992*lim/(1.0-lim),vec3<f32>(2.38095236));return matData(base+27u,lms);}
fn profileBase(id: u32) -> u32 { if (id == 0u) { return 0u; } if (id == 1u) { return PROFILE_STRIDE; } if (id == 2u) { return 2u * PROFILE_STRIDE; } return 3u * PROFILE_STRIDE; }
fn forwardAcesAp0(ap0:vec3<f32>,base:u32)->vec3<f32>{let start=rgbToJmh(ap0,base,false);let chroma=chromaForward(start,base);let compressed=gamutForward(chroma,chroma.x,reachSample(start.z,base),base);return clamp3(jmhToTarget(compressed,base),0.0,p(base,37u));}
fn forwardAces(acescg:vec3<f32>,base:u32)->vec3<f32>{return forwardAcesAp0(acescgToAp0(acescg),base);}
fn imageDisplay(source: vec3<f32>, profile: u32, referenceWhiteEncodedAsLinear203: bool, sourceMode: u32) -> vec3<f32> {
  if (sourceMode == 1u) {
    return forwardAcesAp0(source, profileBase(profile));
  }
  let scale = select(1.0, 1.0 / HDR203_DIFFUSE_WHITE_SCALE, referenceWhiteEncodedAsLinear203);
  let scene = inverseAces(source * scale, 0u * PROFILE_STRIDE);
  return forwardAces(scene, profileBase(profile));
}
fn decodeJhk(j:f32,x:f32,y:f32)->vec3<f32>{let sx=2.0*x-1.0;let sy=2.0*y-1.0;let radius=length(vec2<f32>(sx,sy));let saturation=FITTED_RADIUS_K*(exp(FITTED_RADIUS_D*radius)-1.0);let h=j*J_PEAK;let u=(.007/.525)*saturation;let denominator=sqrt(h*h+(33.0*u)*(33.0*u))+33.0*u;let ja=select(0.0,h*h/denominator,denominator>0.0);let chroma=u*ja;let light=sqrt(max(h*h-66.0*chroma,0.0));var hue=degrees(atan2(-sx,sy));if(hue<0.0){hue+=360.0;}let hr=radians(hue);let ecc=1.0-.0582*cos(hr)-.0258*cos(2.0*hr)-.1347*cos(3.0*hr)+.0289*cos(4.0*hr)-.1475*sin(hr)-.0308*sin(2.0*hr)+.0385*sin(3.0*hr)+.0096*sin(4.0*hr);let colorfulness=chroma*31.7941491565/35.0;let radiusOpponent=colorfulness/(43.0*.8*ecc);let ach=31.7941491565*pow(max(light,0.0)/100.0,1.0/(.525*1.79622776602));let oa=radiusOpponent*cos(hr);let ob=radiusOpponent*sin(hr);let c0=(460.0*(ach+.305)+451.0*oa+288.0*ob)/1403.0;let c1=(460.0*(ach+.305)-891.0*oa-261.0*ob)/1403.0;let c2=(460.0*(ach+.305)-220.0*oa-6300.0*ob)/1403.0;let fl=.466468345005;let lower=400.0*pow(fl*.26/100.0,.42)/(27.13+pow(fl*.26/100.0,.42));let upper=400.0*pow(fl*150.0/100.0,.42)/(27.13+pow(fl*150.0/100.0,.42));let slope=1.68*27.13*fl*pow(fl*150.0/100.0,-.58)/pow(27.13+pow(fl*150.0/100.0,.42),2.0);let response=vec3<f32>(c0,c1,c2)-vec3<f32>(.1);let middle=clamp(response,vec3<f32>(lower),vec3<f32>(upper));let mid=100.0/fl*pow(27.13*middle/(400.0-middle),vec3<f32>(1.0/.42));let low=.26*response/lower;let up=vec3<f32>(150.0)+(response-vec3<f32>(upper))/slope;let cone=select(select(low,mid,response>=vec3<f32>(lower)),up,response>=vec3<f32>(upper));let adapted=cone/vec3<f32>(1.0250779612,.9837843319,.9216705823);return vec3<f32>(1.862067855*adapted.x-1.011254631*adapted.y+.149186775*adapted.z,.387526543*adapted.x+.621447442*adapted.y-.008973985*adapted.z,-.015841499*adapted.x-.034122938*adapted.y+1.049964437*adapted.z)/100.0;}
@compute @workgroup_size(${WORKGROUP}, ${WORKGROUP}) fn main(@builtin(global_invocation_id) id: vec3<u32>) { if(id.x>=settings.width||id.y>=settings.height){return;} let x=select(.5,f32(id.x)/f32(settings.width-1u),settings.width>1u);let y=select(.5,1.0-f32(id.y)/f32(settings.height-1u),settings.height>1u);let radius=length(vec2<f32>(2.0*x-1.0,2.0*y-1.0));let index=id.y*settings.width+id.x;if(radius>1.0){output[index]=vec4<f32>(0.0);return;}let xyz=decodeJhk(settings.j,x,y);let source=xyzToRec2020(xyz);let p3=xyzToP3(xyz);if(any(source<vec3<f32>(-1.0e-8))||any(source>vec3<f32>(AUTHORING_REC2020_PEAK+SOURCE_EPS))||(settings.fullRec2020==0u&&(any(p3<vec3<f32>(-1.0e-8))||any(p3>vec3<f32>(AUTHORING_REC2020_PEAK+SOURCE_EPS))))){output[index]=vec4<f32>(0.0);return;}let scene=inverseAces(xyz,0u*PROFILE_STRIDE);let base=profileBase(settings.profile);output[index]=vec4<f32>(forwardAces(scene,base),1.0); }
@compute @workgroup_size(${WORKGROUP}) fn image_main(@builtin(global_invocation_id) id: vec3<u32>) { if(id.x>=settings.width){return;} let index=id.x; let source=input_pixels[index].xyz; let rgb=imageDisplay(source,settings.profile,settings.reference_white_encoded_as_linear_203!=0u,settings.source_mode); output[index]=vec4<f32>(rgb,1.0); }
`;

export class SliceWebGpuRenderer {
  private readonly gpu: Gpu | undefined;
  private device: Gpu | undefined;
  private pipeline: Gpu | undefined;
  private imagePipeline: Gpu | undefined;
  private parameters: Gpu | undefined;
  private settings: Gpu | undefined;
  private parametersBytes = 0;
  private preparing: Promise<void> | undefined;

  constructor() {
    this.gpu = (globalThis.navigator as Navigator & { gpu?: Gpu } | undefined)?.gpu;
  }

  get available() { return Boolean(this.gpu); }

  private async prepare(parameters: Float32Array) {
    if (this.pipeline) return;
    if (this.preparing) return this.preparing;
    this.preparing = (async () => {
      const adapter = await this.gpu?.requestAdapter();
      if (!adapter) throw new Error("WebGPU adapter unavailable");
      const device = await adapter.requestDevice();
      const usage = gpuBufferUsage();
      this.parametersBytes = parameters.byteLength;
      this.parameters = device.createBuffer({ size: this.parametersBytes, usage: usage.STORAGE | usage.COPY_DST });
      this.settings = device.createBuffer({ size: 32, usage: usage.UNIFORM | usage.COPY_DST });
      device.queue.writeBuffer(this.parameters, 0, parameters.buffer, parameters.byteOffset, parameters.byteLength);
      const module = device.createShaderModule({ code: shader });
      this.pipeline = device.createComputePipeline({ layout: "auto", compute: { module, entryPoint: "main" } });
      this.imagePipeline = device.createComputePipeline({ layout: "auto", compute: { module, entryPoint: "image_main" } });
      this.device = device;
    })();
    try { await this.preparing; } finally { this.preparing = undefined; }
  }

  async render(parameters: Float32Array, viewIndex: number, j: number, width: number, height: number, fullRec2020 = true): Promise<Float32Array> {
    await this.prepare(parameters);
    const device = this.device!;
    const usage = gpuBufferUsage();
    const outputBytes = width * height * 16;
    const output = device.createBuffer({ size: outputBytes, usage: usage.STORAGE | usage.COPY_SRC });
    const readback = device.createBuffer({ size: outputBytes, usage: usage.COPY_DST | usage.MAP_READ });
    const settings = new ArrayBuffer(32);
    const settingsView = new DataView(settings);
    settingsView.setUint32(0, width, true);
    settingsView.setUint32(4, height, true);
    settingsView.setUint32(8, viewIndex, true);
    settingsView.setFloat32(12, j, true);
    settingsView.setUint32(16, 0, true);
    settingsView.setUint32(20, 0, true);
    settingsView.setUint32(24, fullRec2020 ? 1 : 0, true);
    settingsView.setUint32(28, 0, true);
    device.queue.writeBuffer(this.settings, 0, settings);
    const bind = device.createBindGroup({ layout: this.pipeline.getBindGroupLayout(0), entries: [{ binding: 0, resource: { buffer: this.settings } }, { binding: 1, resource: { buffer: this.parameters } }, { binding: 2, resource: { buffer: output } }] });
    const commands = device.createCommandEncoder();
    const pass = commands.beginComputePass();
    pass.setPipeline(this.pipeline);
    pass.setBindGroup(0, bind);
    pass.dispatchWorkgroups(Math.ceil(width / WORKGROUP), Math.ceil(height / WORKGROUP));
    pass.end();
    commands.copyBufferToBuffer(output, 0, readback, 0, outputBytes);
    device.queue.submit([commands.finish()]);
    await readback.mapAsync(gpuMapMode().READ);
    const result = new Float32Array(readback.getMappedRange().slice(0));
    readback.unmap();
    output.destroy();
    readback.destroy();
    return result;
  }

  async renderImage(parameters: Float32Array, viewIndex: number, sourceMode: ImageSourceMode, referenceWhiteEncodedAsLinear203: boolean, pixels: Float32Array): Promise<Float32Array> {
    if (pixels.length === 0 || pixels.length % 3 !== 0) throw new Error("Invalid image pixel buffer.");
    await this.prepare(parameters);
    const device = this.device!;
    const usage = gpuBufferUsage();
    const count = pixels.length / 3;
    const input = new Float32Array(count * 4);
    for (let i = 0; i < count; i += 1) {
      input[i * 4] = pixels[i * 3];
      input[i * 4 + 1] = pixels[i * 3 + 1];
      input[i * 4 + 2] = pixels[i * 3 + 2];
    }
    const inputBytes = input.byteLength;
    const outputBytes = count * 16;
    const inputBuffer = device.createBuffer({ size: inputBytes, usage: usage.STORAGE | usage.COPY_DST });
    const output = device.createBuffer({ size: outputBytes, usage: usage.STORAGE | usage.COPY_SRC });
    const readback = device.createBuffer({ size: outputBytes, usage: usage.COPY_DST | usage.MAP_READ });
    device.queue.writeBuffer(inputBuffer, 0, input.buffer, input.byteOffset, input.byteLength);
    const settings = new ArrayBuffer(32);
    const settingsView = new DataView(settings);
    settingsView.setUint32(0, count, true);
    settingsView.setUint32(4, 1, true);
    settingsView.setUint32(8, viewIndex, true);
    settingsView.setFloat32(12, 0, true);
    settingsView.setUint32(16, 1, true);
    settingsView.setUint32(20, referenceWhiteEncodedAsLinear203 ? 1 : 0, true);
    settingsView.setUint32(24, 1, true);
    settingsView.setUint32(28, sourceMode === "scene-reference-aces" ? 1 : 0, true);
    device.queue.writeBuffer(this.settings, 0, settings);
    const bind = device.createBindGroup({ layout: this.imagePipeline!.getBindGroupLayout(0), entries: [
      { binding: 0, resource: { buffer: this.settings } },
      { binding: 1, resource: { buffer: this.parameters } },
      { binding: 2, resource: { buffer: output } },
      { binding: 3, resource: { buffer: inputBuffer } },
    ] });
    const commands = device.createCommandEncoder();
    const pass = commands.beginComputePass();
    pass.setPipeline(this.imagePipeline!);
    pass.setBindGroup(0, bind);
    pass.dispatchWorkgroups(Math.ceil(count / WORKGROUP));
    pass.end();
    commands.copyBufferToBuffer(output, 0, readback, 0, outputBytes);
    device.queue.submit([commands.finish()]);
    await readback.mapAsync(gpuMapMode().READ);
    const result = new Float32Array(readback.getMappedRange().slice(0));
    readback.unmap();
    inputBuffer.destroy(); output.destroy(); readback.destroy();
    const rgb = new Float32Array(count * 3);
    for (let i = 0; i < count; i += 1) rgb.set(result.subarray(i * 4, i * 4 + 3), i * 3);
    return rgb;
  }
}
