"""Required compiler checks with positive and negative scope controls."""
from importlib.resources import files
import json
import re
import subprocess
import unittest
from tests.support import oracle
from tests.support.dctl import body

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
            command += ['-x', 'cl', '-cl-std=CL1.2', '-fsyntax-only', '-Wall', '-Werror', '-Wno-unused-function', '-']
            prefix = OPENCL
        else:
            command += ['-x', 'c++', '-std=c++17', '-fsyntax-only', '-Wall', '-Werror', '-Wno-unused-function', '-']
            prefix = (files('tests.dctl') / 'float3.h').read_text()
        return subprocess.run(command, input=prefix + source, text=True, capture_output=True)

    def test_helpers_compile_without_ui_globals_in_both_editions(self):
        for filename in ('Perceptual-Grade.dctl', 'Perceptual-Grade-zh-HANS.dctl'):
            source = body((oracle.RESOURCES / filename).read_text())
            for language in ('cl', 'cpp'):
                with self.subTest(filename=filename, language=language):
                    result = self.compile(language, source)
                    self.assertEqual(result.returncode, 0, result.stderr)

    def test_scope_checker_accepts_locals_and_rejects_hidden_globals(self):
        for language in ('cl', 'cpp'):
            self.assertEqual(self.compile(language, 'float helper(float globalExposure) { return globalExposure; }').returncode, 0)
            self.assertNotEqual(self.compile(language, 'float helper() { return globalExposure; }').returncode, 0)

    def test_intrinsics_use_documented_dctl_names(self):
        # Resolve's DCTL Developer reference, section 8 (Supporting math
        # functions). Host aliases must not invent extra DCTL intrinsics.
        supported={'_fabs','_sqrtf','_sinf','_cosf','_fmaxf','_fminf','_powf',
                   '_exp2f','_floorf','_logf','_expf','_fmaf','_atan2f',
                   '_tanhf','_sinhf','_asinhf'}
        for filename in ('Perceptual-Grade.dctl','Perceptual-Grade-zh-HANS.dctl'):
            with self.subTest(filename=filename):
                source=re.sub(r'//[^\n]*|/\*.*?\*/','',body((oracle.RESOURCES/filename).read_text()),flags=re.S)
                used=set(re.findall(r'\b(_[A-Za-z]\w*)\s*\(',source))
                self.assertFalse(used-supported,used-supported)
        for language in ('cl','cpp'):
            result=self.compile(language,'float helper(float x) { return _nextafterf(x,0.0f); }')
            self.assertNotEqual(result.returncode,0)
            self.assertIn('_nextafterf',result.stderr)

    def test_metal_reserved_identifiers(self):
        source = re.sub(r'//[^\n]*', '', body(oracle.SOURCE))
        forbidden = {'kernel', 'vertex', 'fragment', 'device', 'constant', 'thread', 'threadgroup', 'threadgroup_imageblock', 'ray_data', 'object_data'}
        self.assertFalse(set(re.findall(r'\b[A-Za-z_]\w*\b', source)) & forbidden)
