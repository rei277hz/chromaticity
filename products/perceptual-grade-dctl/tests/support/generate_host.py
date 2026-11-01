"""Assemble a float32 C++ oracle from generated DCTL."""
import argparse
from pathlib import Path
from tests.support.dctl import body, controls, model_call


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dctl', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    source = args.dctl.read_text()
    ui = controls(source)
    declarations = '\n'.join(('int' if item['type'] in ('DCTLUI_SLIDER_INT', 'DCTLUI_COMBO_BOX') else 'float') + ' ' + item['name'] + ';' for item in ui)
    formats = ''.join('%d' if item['type'] in ('DCTLUI_SLIDER_INT', 'DCTLUI_COMBO_BOX') else '%f' for item in ui)
    addresses = ','.join('&'+item['name'] for item in ui)
    args.output_dir.mkdir(parents=True, exist_ok=True)
    (args.output_dir / 'kernel.h').write_text(body(source))
    (args.output_dir / 'host.cpp').write_text(
        '#include "float3.h"\n#include "kernel.h"\n#include <stdio.h>\n#include <string.h>\n' + declarations + '\n' +
        '__DEVICE__ float3 transform('+source.split('__DEVICE__ float3 transform(',1)[1]+'\n'+
        'PGModel model() { PGModel m=' + model_call(source) + ';m.direction=direction;return m; }\n' +
        'bool settings() { return scanf("' + formats + '",' + addresses + ') == ' + str(len(ui)) + '; }\n' +
        '''int main(int argc,char** argv) {
    if(argc!=2)return 2;
    const char* mode=argv[1];
    while(settings()) {
        float3 v;if(scanf("%f%f%f",&v.x,&v.y,&v.z)!=3)return 2;
        PGModel m=model();PGValue result=pg_value(v,1);
        if(!strcmp(mode,"grade"))result.v=pg_grade(v,m);
        else if(!strcmp(mode,"pixel")) {
            int width,height,x,y;if(scanf("%d%d%d%d",&width,&height,&x,&y)!=4)return 2;
            result.v=transform(width,height,x,y,v.x,v.y,v.z);
        }
        else if(!strcmp(mode,"forward_native"))result.v=pg_forward_native(v,m);
        else if(!strcmp(mode,"inverse_native"))result=pg_inverse_native(v,m);
        else if(!strcmp(mode,"selected")) {result.v=pg_apply_pixel(v,m,direction);result.valid=m.valid&&(!direction||m.invertible);}
        else if(!strcmp(mode,"configuration"))result.v=make_float3((float)m.valid,(float)m.invertible,0.0f);
        else if(!strcmp(mode,"linear"))result.v=pg_linear(v,m);
        else if(!strcmp(mode,"nonlinear"))result=pg_nonlinear_eval(v,m);
        else if(!strcmp(mode,"inverse"))result=pg_inverse_grade_eval(v,m);
        else if(!strcmp(mode,"inverse_nonlinear"))result=pg_inverse_nonlinear_eval(v,m);
        else if(!strcmp(mode,"entry")) { PGState state=pg_enter(v);result.v=state.q;result.ja=state.e; }
        else if(!strcmp(mode,"export")) {
            PGState state;state.q=v;if(scanf("%f",&state.e)!=1)return 2;
            result.v=pg_export(state);
        }
        else if(!strcmp(mode,"capacity"))result.v=make_float3(pg_capacity(v.x,v.y),0,0);
        else if(!strcmp(mode,"physical_capacity"))result.v=make_float3(pg_physical_capacity(v.x,v.y),0,0);
        else if(!strcmp(mode,"decode")) {
            PGState state;state.q=v;if(scanf("%f",&state.e)!=1)return 2;
            result=pg_decode_state(state);
        }
        else if(!strcmp(mode,"remap"))result.v=make_float3(pg_remap(v.x,m),0,0);
        else if(!strcmp(mode,"inverse_tone"))result.v=make_float3(pg_inverse_tone_height(v.x,m),0,0);
        else if(!strcmp(mode,"safe_white"))result.v=pg_safe_source_xy(v.x,v.y);
        else if(!strcmp(mode,"next_down"))result.v=make_float3(pg_next_down(v.x),pg_next_down(v.y),pg_next_down(v.z));
        else if(!strcmp(mode,"input_repair"))result.v=pg_input_repair(v);
        else return 2;
        printf("%.10g %.10g %.10g %d %.10g\\n",result.v.x,result.v.y,result.v.z,result.valid,result.ja);
    }
    return feof(stdin)?0:2;
}
''')


if __name__ == '__main__':
    main()
