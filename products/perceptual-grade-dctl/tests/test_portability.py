"""Compile every localized transform and its helpers with the portable GPU ABI."""
from importlib.resources import files
import json
import re
import subprocess
import unittest

from tests.support import oracle
from tests.support.dctl import ALL_STAGES, LOCALES, body, controls, entry

OPENCL = '''#define DEVICE_IS_OPENCL 1
#define __DEVICE__ static inline
#define __CONSTANT__ __constant
#define __CONSTANTREF__ __constant
static inline float3 make_float3(float x,float y,float z) {return (float3)(x,y,z);}
#define _fabs fabs
#define _sqrtf sqrt
#define _sinf sin
#define _cosf cos
#define _fmaxf fmax
#define _fminf fmin
#define _powf pow
#define _exp2f exp2
#define _floorf floor
#define _logf log
#define _expf exp
#define _fmaf fma
#define _atan2f atan2
#define _tanhf tanh
#define _sinhf sinh
#define _asinhf asinh
'''


class PortabilityTests(unittest.TestCase):
    def compile(self, language, source):
        command = json.loads((files('tests.dctl') / 'compilers.json').read_text())[language]
        if language == 'cl':
            command += ['-x', 'cl', '-cl-std=CL1.2']
            prefix = OPENCL
        else:
            command += ['-x', 'c++', '-std=c++17']
            prefix = (files('tests.dctl') / 'float3.h').read_text()
        command += ['-fsyntax-only', '-Wall', '-Werror', '-Wno-unused-function', '-']
        return subprocess.run(command, input=prefix + source, text=True, capture_output=True)

    def test_localized_entry_and_helpers_compile(self):
        for stage in ALL_STAGES:
            for locale in LOCALES:
                source = oracle.source(stage, locale)
                # UI globals exist only inside Resolve's entry point. Using macros
                # here checks integer/float types without OpenCL global variables.
                macros = []
                for item in controls(source):
                    default = item["default"]
                    value = f"{default}f" if item["type"] == "DCTLUI_SLIDER_FLOAT" else str(int(default))
                    macros.append(f"#define {item['name']} {value}")
                program = body(source) + "\n" + "\n".join(macros) + "\n" + entry(source)
                for lang in ("cl", "cpp"):
                    with self.subTest(stage=stage, locale=locale, language=lang):
                        result = self.compile(lang, program)
                        self.assertEqual(result.returncode, 0, result.stderr)

    def test_no_reserved_names_or_undocumented_intrinsics(self):
        reserved = {"kernel", "vertex", "fragment", "device", "constant", "thread",
                    "threadgroup", "threadgroup_imageblock", "ray_data", "object_data"}
        supported = set(re.findall(r"^#define (_\w+)", OPENCL, re.M))
        for stage in ALL_STAGES:
            with self.subTest(stage=stage):
                source = re.sub(r"//[^\n]*|/\*.*?\*/", "", body(oracle.source(stage)), flags=re.S)
                self.assertFalse(set(re.findall(r"\b\w+\b", source)) & reserved)
                calls = set(re.findall(r"\b(_[A-Za-z]\w*)\s*\(", source))
                self.assertFalse(calls - supported, calls - supported)
                # Resolve UI injection can make bare helper identifiers collide with controls.
                source = re.sub(r"typedef\s+struct\s*\{[^}]*\}\s*\w+\s*;", "", source)
                source = re.sub(r"\.\s*\w+", "", source)
                self.assertFalse(set(re.findall(r"\b\w+\b", source))
                                 & {item["name"] for item in oracle.ui(stage)})
