"""Build Perceptual Grade localized DCTLs."""
from pathlib import Path
import argparse,json,tomllib
import numpy as np
from importlib.resources import files
from color_tools.perceptual_grade_core.model.boundary_resource import load_data
from .dctl_boundary import generate as boundary_source

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output-dir",type=Path,required=True)
parser.add_argument("--source-dir",type=Path,required=True)
parser.add_argument("--color-source",type=Path,required=True)
parser.add_argument("--metadata",type=Path,required=True)
args=parser.parse_args()
OUTPUT=args.output_dir
SOURCE=args.source_dir
OUTPUT.mkdir(parents=True,exist_ok=True)
TONES = 'SMWH'
from color_tools.perceptual_grade_core.localization.catalogs import tr, CATALOGS
from color_tools.perceptual_grade_core.model import linear as linear_math
UI_SPEC = json.loads((SOURCE/'ui-spec.json').read_text(encoding='utf-8'))
float_sliders = sum(item['type']=='DCTLUI_SLIDER_FLOAT' for item in UI_SPEC)
if float_sliders>64:
    raise ValueError(f'DCTL supports at most 64 float sliders; this specification has {float_sliders}')
VERSION = tomllib.loads(args.metadata.read_text())['version']


def translated_ui(language):
    result = []
    for spec in UI_SPEC:
        item = {k: v for k, v in spec.items() if k not in {'label_id', 'tooltip_id'}}
        item['label'] = tr(spec['label_id'], locale=language)
        item['tooltip'] = tr(spec['tooltip_id'], locale=language)
        if spec['options']:
            item['options'] = [spec['options'][0], [tr(key, locale=language) for key in spec['options'][1]]]
        result.append(item)
    return result



def number(x):
    s = format(x, '.12g')
    if '.' not in s and 'e' not in s: s += '.0'
    return s + 'f'

INTRO = f'''// Perceptual Grade {VERSION} | Linear XYZ in/out; D65, reference white 203 nits.
// Direct per-pixel forward/inverse, with native AP1 [0,1024] input repair.
// Original compact D65 cube rays; no baked RGB LUT.
// Raw appearance grading; validated fixed-J_A/hue cube export (24 refinements).
// Inverse: three candidates, eight bounded Stage-3 iterations; scalar tone
// inversion uses at most 80 safeguarded Newton/bisection evaluations.
// Singular inverse Stage 1 or invalid CAT16 adaptation displays ERROR stripes.
// Paired a/b J/C controls use direct signed coefficients.
// Highlight Low/High/a/b J/C controls retain their integer-slider policy.
'''

def ui_header(controls):
    result=INTRO
    for c in controls:
        kind=c['type']
        if kind == 'DCTLUI_SLIDER_FLOAT': args=', '.join(number(c[k]) for k in ('default','min','max','step'))
        elif kind == 'DCTLUI_SLIDER_INT': args=', '.join(str(c[k]) for k in ('default','min','max','step'))
        elif kind == 'DCTLUI_VALUE_BOX': args=str(c['default'])
        else: args=str(c['default'])+', {'+', '.join(c['options'][0])+'}, {'+', '.join(c['options'][1])+'}'
        result += f"DEFINE_UI_PARAMS({c['name']}, {c['label']}, {kind}, {args})\n"
    for c in controls:
        tooltip=json.dumps(c['tooltip'], ensure_ascii=True)
        result += f"DEFINE_UI_TOOLTIP({c['label']}, {tooltip})\n"
    return result


structs = '''
typedef struct { float fl; float aw; float pivotJ; float lowJ; } PGViewing;
typedef struct { float s; float m; float w; float h; } PGFour;
typedef struct { float a; float b; float c; float d; float e; } PGWeights;
typedef struct { PGFour z; PGFour norm; float width; } PGKernel;
typedef struct { PGFour a; PGFour b; PGKernel curveKernel; int zeroBlack; } PGFamily;
typedef struct { PGFour c; PGFour q; PGFour a; PGFour b; PGKernel curveKernel; } PGResponseFamily;
typedef struct { float c; float q; float a; float b; } PGCoefficients;
typedef struct { float c; float q; float a; float b; float adaptanceWeight; } PGDrivers;
typedef struct { float3 adaptance; float3 concentration; PGCoefficients light; PGCoefficients radius; float hue; float adaptanceStrength; } PGAdjustment;
typedef struct {
    float3 ws; float3 wd; float3 wc;
    ColorMat adapt; ColorMat lin; PGViewing view;
    PGFour input; PGFour target; PGFour residual; PGKernel remap;
    PGFamily adaptance; PGResponseFamily light; PGResponseFamily radius;
    PGFour hueHeights; PGFour concentrationAHeights; PGFour concentrationBHeights; PGKernel hueCurve;
    float radiusBase; float hueByChroma; float hueByBend; float adaptanceStrength;
    float black; float qHigh; float tailSlope; float exposure;
    float highJ; float effectiveRefNits; float effectivePeakNits;
    int remapActive; int tonalActive; int active; int linearActive; int ordered;
    int valid; int invertible; int directional; int direction;
} PGModel;
typedef struct { float3 v; int valid; float ja; } PGValue;
typedef struct { float3 q; float e; } PGState;
'''
def white_guard_source():
    """Emit the shared convex CAT16 domain, with no per-pixel eigensolver."""
    polygon = linear_math.WHITE_POLYGON
    lines = ['// Generated from model.linear.WHITE_PLANES and WHITE_POLYGON.',
             '__DEVICE__ float3 pg_source_vertex(int i) {']
    for i, (x, y) in enumerate(polygon):
        lines.append(f'    if(i=={i})return make_float3({number(x)},{number(y)},0.0f);')
    lines += ['    return make_float3(0.3127f,0.329f,0.0f);', '}',
              '__DEVICE__ float3 pg_safe_source_xy(float x,float y) {',
              '    x=_fminf(.9f,_fmaxf(0.0f,x)); y=_fminf(.9f,_fmaxf(0.0f,y));',
              '    float3 p=make_float3(x,y,0.0f);']
    conditions = [f'({number(a)}*x+{number(b)}*y+{number(c)}>=0.0f)'
                  for a,b,c in linear_math.WHITE_PLANES]
    lines += ['    if('+ '&&'.join(conditions)+')return p;',
              '    float distance=1e20f; float3 best=p;',
              f'    for(int i=0;i<{len(polygon)};i++) {{',
              f'        float3 a=pg_source_vertex(i),b=pg_source_vertex((i+1)%{len(polygon)});',
              '        float3 d=b-a; float t=_fminf(1.0f,_fmaxf(0.0f,color_dot(p-a,d)/color_dot(d,d)));',
              '        // Fused projection avoids amplifying xy rounding in small CAT16 cones.',
              '        float3 q=make_float3(_fmaf(d.x,t,a.x),_fmaf(d.y,t,a.y),0.0f); float e=color_dot(p-q,p-q);',
              '        if(e<distance){distance=e;best=q;}',
              '    }', '    return best;', '}', '']
    return '\n'.join(lines)


base=(SOURCE/'foundation.dctlh').read_text()
base=base.replace('__DEVICE__ float3 pg_white(', white_guard_source()+'__DEVICE__ float3 pg_white(')
with np.load(files('color_tools.perceptual_grade_core.model')/'d65_boundary.npz',allow_pickle=False) as cache:
    boundary,constant_bytes=boundary_source(load_data({key:cache[key] for key in cache.files}))
boundary_math=(SOURCE/'boundary.dctlh').read_text()
boundary+=boundary_math
boundary+='''
__DEVICE__ float pg_physical_capacity(float JA,float hue) {
    if(JA<=0.0f||JA>=PG_WHITE)return 0.0f;
    float t=_powf(JA/PG_WHITE,1.0f/PG_GAMMA);
    return PG_RW*t*(1.0f-t)*pg_capacity(t,hue);
}
''' 
tail=(SOURCE/'core.dctlh').read_text()
overlay=(SOURCE/'overlay.dctlh').read_text()

def four(prefix): return 'pg_four(' + ','.join(prefix.format(t=t) for t in TONES) + ')'
call = '''pg_model(pg_white(srcWhite,srcX,srcY),pg_white(0,0.0f,0.0f),globalExposure,
        la,ls,-le,ba,bs,-be,inputBlack,pg_four(inputShadows,inputMidtones,inputWhite,inputHighlights),remapFit,
'''
call += '        '+four('tone{t}AdaptanceA')+','+four('tone{t}AdaptanceB')+',adaptanceFit,adaptanceStrength,\n'
for receiver, fit_name in [('J','lightnessFit'),('C','chromaFit')]:
    fields=[four('tone{t}'+driver+'To'+receiver) for driver in ('High','Low')]
    fields += [four('tone{t}'+axis+'To'+receiver) for axis in ('a','b')]
    call += '        '+','.join(fields)+','+fit_name+',\n'
call += '        '+four('tone{t}Hue')+','+four('tone{t}ConcentrationA')+','+four('tone{t}ConcentrationB')+',hueFit,globalChromaGain,globalHighChromaHue,globalLowChromaHue,pg_selected_peak(peakNits))'
transform = '''__DEVICE__ float3 transform(int p_Width,int p_Height,int p_X,int p_Y,float p_R,float p_G,float p_B) {
    // Resolve UI globals are referenced only here, never by helper functions.
    PGModel m='''+call+''';
    m.direction=direction;
    float3 output;
    if(!m.valid||(direction&&!m.invertible)||!color_finite3(make_float3(p_R,p_G,p_B)))
        output=pg_diagnostic(p_Width,p_Height,p_X,p_Y);
    else {
        float3 result=pg_apply_pixel(make_float3(p_R,p_G,p_B),m,direction);
        output=pg_overlay(result,p_Width,p_Height,p_X,p_Y,overlayMode,m,refTriangle,1.0f);
    }
    // Keep the entry return explicit for Resolve's source-level type detection.
    return make_float3(output.x,output.y,output.z);
}
'''
source='/* PG_NUMERICAL_BEGIN */\n'+args.color_source.read_text()+structs+base+boundary+(SOURCE/'math.dctlh').read_text()+tail+(SOURCE/'inverse.dctlh').read_text()+overlay+'/* PG_NUMERICAL_END */\n'+transform
for locale in CATALOGS:
    localized = translated_ui(locale)
    suffix = '' if locale == 'en' else '-' + locale.replace('_', '-')
    (OUTPUT/('Perceptual-Grade'+suffix+'.dctl')).write_text(ui_header(localized)+source,encoding='utf-8')
print('Built', len(CATALOGS), 'DCTL editions;', len(UI_SPEC), 'UI controls.')
