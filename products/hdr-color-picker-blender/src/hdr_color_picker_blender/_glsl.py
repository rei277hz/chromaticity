"""Blender compute implementation of the legacy scalar picker equations."""
import numpy as np
from ..color_core import aces2
from ..hdr_color_picker_core import (
    ADAPTATION,
    CAT16_INVERSE,
    OPPONENT_TO_COMPRESSED,
    RADIUS_CUBIC,
    RADIUS_K,
)


def _scalar(x):
    result = format(float(np.float32(x)), '.9g')
    return result if '.' in result or 'e' in result else result+'.0'


def _matrix_function(name, matrix):
    rows = [f'dot(vec3({",".join(map(_scalar, row))}),v)' for row in matrix]
    return 'vec3 '+name+'(vec3 v){return vec3('+','.join(rows)+');}\n'


def source():
    header = ''
    for name, matrix in [('toRec2020', aces2.XYZ_TO_REC2020), ('toLms', aces2.RGB_TO_LMS),
                         ('toAab', aces2.AAB_FROM_RGB_A), ('fromAab', aces2.AAB_TO_RGB_A),
                         ('toAp0', aces2.LMS_TO_AP0), ('toAcescg', aces2.AP0_TO_ACESCG),
                         ('fromCat16', CAT16_INVERSE), ('toCompressed', OPPONENT_TO_COMPRESSED)]:
        header += _matrix_function(name, matrix)
    header += 'const vec3 ADAPTATION=vec3('+','.join(map(_scalar, ADAPTATION))+');\n'
    header += 'const float RADIUS_K='+_scalar(RADIUS_K)+';\n'
    header += 'const float RADIUS_CUBIC='+_scalar(RADIUS_CUBIC)+';\n'
    return header+MATH


MATH = r'''
const float JMAX=283.249878;
float lookup(int i){return texelFetch(tables,ivec2(i%256,i/256),0).r;}
float reachSample(float hue){
    float h=mod(hue,360.0);int i=int(floor(h))+1;
    return mix(lookup(i),lookup(i+1),fract(h));
}
vec3 cuspSample(float hue){
    float h=mod(hue,360.0);int i=int(floor(h))+1;
    int lo=max(i-1,0),hi=min(i+2,361);
    for(int pass=0;pass<2;pass++){
        if(lo+1>=hi)break;
        if(h>lookup(1452+i))lo=i;else hi=i;
        i=(lo+hi)/2;
    }
    int a=hi-1,b=hi;
    float t=clamp((h-lookup(1452+a))/(lookup(1452+b)-lookup(1452+a)),0.0,1.0);
    return mix(vec3(lookup(363+3*a),lookup(364+3*a),lookup(365+3*a)),
               vec3(lookup(363+3*b),lookup(364+3*b),lookup(365+3*b)),t);
}
float solveJ(float j,float m,float focus,float gain){
    float ms=m/gain,a=ms/focus;
    if(j<focus){float b=1.0-ms,c=-j;return -2.0*c/(b+sqrt(max(0.0,b*b-4.0*a*c)));}
    float b=-(1.0+ms+JMAX*a),c=JMAX*ms+j;
    return -2.0*c/(b-sqrt(max(0.0,b*b-4.0*a*c)));
}
float focusGain(float j,float cuspJ){
    float threshold=.7*cuspJ+.3*JMAX;
    if(j<=threshold)return 1.0;
    float gain=log((JMAX-threshold)/max(.0001,JMAX-j))/log(10.0);
    return gain*gain+1.0;
}
vec3 gamutInverse(vec3 jmh,float jx){
    float j=jmh.x,m=jmh.y,h=jmh.z;
    if(m<=0.0||j>JMAX)return vec3(j,0,h);
    vec3 cusp=cuspSample(h);
    float focus=mix(cusp.x,40.816883,min(1.0,1.3-cusp.x/JMAX));
    float gain=1051.56519*focusGain(jx,cusp.x);
    float js=solveJ(j,m,focus,gain),sb=js<focus?js:JMAX-js;
    float slope=sb*(js-focus)/(focus*gain),jc=solveJ(cusp.x,cusp.y,focus,gain);
    float lower=jc*pow(js/jc,.826446235)/(cusp.x/cusp.y-slope);
    float upper=cusp.y*(JMAX-jc)*pow((JMAX-js)/(JMAX-jc),cusp.z)/(slope*cusp.y+JMAX-cusp.x);
    float s=.12*cusp.y,blend=max(0.0,s-abs(lower-upper))/s;
    float boundary=min(lower,upper)-blend*blend*blend*s/6.0;
    if(boundary<=0.0)return vec3(j,0,h);
    float reach=JMAX*pow(js/JMAX,.879464149)/(JMAX/reachSample(h)-slope);
    float proportion=max(boundary/reach,.75),threshold=proportion*boundary;
    float remapped=m;
    if(proportion<1.0&&m>threshold){
        float ro=reach-threshold,go=boundary-threshold;
        float scale=ro/(ro/go-1.0),nd=(m-threshold)/scale;
        remapped=threshold+scale*(nd>=1.0?1.0:-nd/(nd-1.0));
    }
    return vec3(js+remapped*slope,remapped,h);
}
vec3 gamutInverseOcio(vec3 jmh){
    vec3 first=gamutInverse(jmh,jmh.x);
    if(jmh.x<=.7*cuspSample(jmh.z).x+.3*JMAX)return first;
    return gamutInverse(jmh,first.x);
}
float toneInverse(float j){
    if(j==0.0)return 0.0;
    float a=.0323680267*pow(abs(j)*.00999999978,.879464149);
    float y=pow(27.1299992*a/(1.0-a),2.3809523809523809);
    float z=clamp(y/.79370057210326195,0.0,10.1325417);
    float ht=.5*(z+sqrt(z*(.15999999642372131+z)));
    float yo=4.6796021847256952/(pow(10.1729107/ht,.86956523541917463)-1.0);
    float fly=pow(abs(yo),.42);
    return sign(j)*100.0*pow(fly/(27.1299992+fly)*30.8946857,1.13705599);
}
float toeInverse(float x,float limit,float k1,float k2){
    k2=max(k2,.001);k1=sqrt(k1*k1+k2*k2);
    float k3=(limit+k1)/(limit+k2);
    return x>limit?x:(x*x+k1*x)/(k3*(x+k2));
}
vec3 chromaInverse(vec3 jmh){
    float jts=jmh.x,mcp=jmh.y,h=jmh.z,j=toneInverse(jts);
    if(mcp==0.0)return vec3(j,0,h);
    float r=radians(h),co=cos(r),si=sin(r);
    float mn=co*28.177105004310604+(2.0*co*co-1.0)*40.918782982468606
        +(4.0*co*co*co-3.0*co)*19.588056175708772+si*36.435131137728689
        +(2.0*co*si)*-15.832440585136412+(3.0*si-4.0*si*si*si)*22.842479106426239+191.63428819274904;
    float nj=jts/JMAX,snj=max(1.0-nj,0.0),limit=pow(nj,.879464149)*reachSample(h)/mn;
    float m=toeInverse(mcp/mn,limit,nj*10.3199997,snj);
    m=limit-toeInverse(limit-m,limit-.001,snj*.402999997,sqrt(nj*nj+.000500000024));
    m*=mn*pow(jts/j,-.879464149);
    return vec3(j,m,h);
}
vec3 inverseAces(vec3 xyz){
    vec3 lms=toLms(clamp(toRec2020(xyz),vec3(0),vec3(10)));
    vec3 power=pow(abs(lms),vec3(.42));
    vec3 aab=toAab(sign(lms)*power/(vec3(27.1299992)+power));
    vec3 jmh=vec3(0);
    if(aab.x>0.0){
        float h=mod(degrees(atan(aab.z,aab.y))+360.0,360.0);
        jmh=vec3(100.0*pow(aab.x,1.13705599),length(aab.yz),h);
    }
    jmh=chromaInverse(gamutInverseOcio(jmh));
    float r=radians(jmh.z);
    vec3 ra=fromAab(vec3(pow(jmh.x*.00999999978,.879464149),jmh.y*cos(r),jmh.y*sin(r)));
    vec3 lim=min(abs(ra),vec3(.99000001));
    lms=sign(ra)*pow(27.1299992*lim/(1.0-lim),vec3(2.38095236));
    return clamp(toAcescg(toAp0(lms)),vec3(0),vec3(4096));
}
float inverseResponse(float v){
    v-=.1;float fl=.46646834500532247;
    float lp=pow(fl*.26/100.0,.42),hp=pow(fl*150.0/100.0,.42);
    float lower=400.0*lp/(27.13+lp),upper=400.0*hp/(27.13+hp);
    float slope=1.68*27.13*fl*pow(fl*150.0/100.0,-.58)/pow(27.13+hp,2.0);
    if(v<lower)return .26*v/lower;
    if(v>upper)return 150.0+(v-upper)/slope;
    return 100.0/fl*pow(27.13*v/(400.0-v),1.0/.42);
}
vec3 decodeJhk(float j,float x,float y){
    float sx=2.0*x-1.0,sy=2.0*y-1.0,radius=length(vec2(sx,sy));
    float t=radius/sqrt((1.0-radius)*(1.0+radius));
    float scale=sqrt(3.0*RADIUS_CUBIC);
    float radius_scale=RADIUS_CUBIC==0.0?t:(2.0/scale)*sinh(asinh(1.5*scale*t)/3.0);
    float saturation=RADIUS_K*radius_scale;
    float h=j*217.2768649129496,achromatic_u=(.007/.525)*saturation;
    float denominator=length(vec2(h,33.0*achromatic_u))+33.0*achromatic_u;
    float ja=denominator>0.0?h*h/denominator:0.0,chroma=achromatic_u*ja;
    float light=sqrt(max(0.0,h*h-66.0*chroma));
    float hr=atan(-sx,sy);
    float ecc=1.0-.0582*cos(hr)-.0258*cos(2.0*hr)-.1347*cos(3.0*hr)+.0289*cos(4.0*hr)
        -.1475*sin(hr)-.0308*sin(2.0*hr)+.0385*sin(3.0*hr)+.0096*sin(4.0*hr);
    float radiusOpponent=(chroma*31.7941491565276/35.0)/(43.0*.8*ecc);
    float ach=31.7941491565276*pow(light/100.0,1.0/(.525*1.7962277660168378));
    vec3 c=toCompressed(vec3(ach+.305,radiusOpponent*cos(hr),radiusOpponent*sin(hr)));
    vec3 cone=vec3(inverseResponse(c.x),inverseResponse(c.y),inverseResponse(c.z));
    return fromCat16(cone/ADAPTATION)/100.0;
}
vec3 xyzToP3(vec3 v){
    return vec3(dot(vec3(2.493496911941425,-.931383617919124,-.402710784450717),v),
        dot(vec3(-.829488969561575,1.762664060318347,.023624685841944),v),
        dot(vec3(.035845830243784,-.076172389268042,.956884524007687),v));
}
void main(){
    ivec2 id=ivec2(gl_GlobalInvocationID.xy);
    if(any(greaterThanEqual(id,dimensions)))return;
    float x=dimensions.x==1?.5:float(id.x)/float(dimensions.x-1);
    float y=dimensions.y==1?.5:1.0-float(id.y)/float(dimensions.y-1);
    if(j_value<0.0||j_value>1.0||length(vec2(2.0*x-1.0,2.0*y-1.0))>=1.0){
        imageStore(output_pixels,id,vec4(0));return;
    }
    vec3 xyz=decodeJhk(j_value,x,y),source=toRec2020(xyz),p3=xyzToP3(xyz);
    float peak=10.0/2.03;
    bool valid=!any(isnan(source))&&!any(isinf(source))
        &&!any(lessThan(source,vec3(-1e-8)))&&!any(greaterThan(source,vec3(peak+1e-7)));
    if(full_rec2020==0)valid=valid&&!any(lessThan(p3,vec3(-1e-8)))&&!any(greaterThan(p3,vec3(peak+1e-7)));
    if(!valid){imageStore(output_pixels,id,vec4(0));return;}
    vec3 scene=inverseAces(xyz);
    if(any(isnan(scene))||any(isinf(scene)))imageStore(output_pixels,id,vec4(0));
    else imageStore(output_pixels,id,vec4(scene,1));
}
'''
