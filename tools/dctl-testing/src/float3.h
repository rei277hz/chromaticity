// Float-only host shims; the numerical implementation comes from generated DCTL.
#include <math.h>
struct float3 { float x,y,z; };
inline float3 make_float3(float x,float y,float z) { return {x,y,z}; }
inline float3 operator+(float3 a,float3 b) { return {a.x+b.x,a.y+b.y,a.z+b.z}; }
inline float3 operator-(float3 a,float3 b) { return {a.x-b.x,a.y-b.y,a.z-b.z}; }
inline float3 operator*(float3 a,float3 b) { return {a.x*b.x,a.y*b.y,a.z*b.z}; }
inline float3 operator/(float3 a,float3 b) { return {a.x/b.x,a.y/b.y,a.z/b.z}; }
inline float3 operator*(float3 a,float b) { return {a.x*b,a.y*b,a.z*b}; }
inline float3 operator/(float3 a,float b) { return {a.x/b,a.y/b,a.z/b}; }
#define __DEVICE__ static inline
#define __CONSTANT__ static const
#define __CONSTANTREF__ const
#define _fabs fabsf
#define _sqrtf sqrtf
#define _sinf sinf
#define _cosf cosf
#define _fmaxf fmaxf
#define _fminf fminf
#define _powf powf
#define _exp2f exp2f
#define _floorf floorf
#define _logf logf
#define _expf expf
#define _fmaf fmaf
#define _atan2f atan2f
#define _tanhf tanhf
#define _sinhf sinhf
#define _asinhf asinhf
