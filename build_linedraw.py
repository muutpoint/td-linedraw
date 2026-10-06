"""
linedraw for TouchDesigner  --  builder script
A GLSL port of LingDong-/linedraw (https://github.com/LingDong-/linedraw, MIT):
contours + wobbly hatching that look like a pen-plotter drawing, as a live TOP.

HOW TO RUN (TouchDesigner 2023.11000 or newer)
  1. Create a Text DAT in the network where you want the component.
  2. Paste this whole file into it.
  3. Right-click the DAT > Run Script.
  -- or from the Textport:  exec(open(r'C:/path/to/build_linedraw.py').read())

It creates:
  linedraw1       the component (Image mode by default: wire any TOP into it)
  linedraw_demo   a small 3D scene showing Scene mode (render-aware) and Image mode side by side
"""

BUILD_COMPONENT = True
BUILD_DEMO = True

SHADERS = {}
SHADERS['levels'] = r'''
// ---------------------------------------------------------------------------
// linedraw common helpers (hashing + noise). Self-contained, no TD noise calls.
// Port of LingDong-/linedraw (MIT) to GLSL by Ro Mayz.
// ---------------------------------------------------------------------------
uint ldHash(uint x)
{
	x ^= x >> 16; x *= 0x7feb352dU;
	x ^= x >> 15; x *= 0x846ca68bU;
	x ^= x >> 16;
	return x;
}
float ldHash21(ivec2 p, uint s)
{
	uint h = ldHash(uint(p.x) * 1597334677U ^ ldHash(uint(p.y) ^ (s * 0x9E3779B9U)));
	return float(h) * (1.0 / 4294967295.0);
}
float ldHash11(float x, uint s)
{
	return ldHash21(ivec2(int(floor(x)), 0), s);
}
vec2 ldGrad(ivec2 p, uint s)
{
	float a = ldHash21(p, s) * 6.28318530718;
	return vec2(cos(a), sin(a));
}
// gradient noise, roughly [-0.7, 0.7]
float ldGNoise(vec2 x, uint s)
{
	ivec2 i = ivec2(floor(x));
	vec2 f = fract(x);
	vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
	float a = dot(ldGrad(i, s), f);
	float b = dot(ldGrad(i + ivec2(1, 0), s), f - vec2(1.0, 0.0));
	float c = dot(ldGrad(i + ivec2(0, 1), s), f - vec2(0.0, 1.0));
	float d = dot(ldGrad(i + ivec2(1, 1), s), f - vec2(1.0, 1.0));
	return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
// 4-octave fbm like p5.js noise(), roughly [-0.5, 0.5]
float ldFbm(vec2 x, uint s)
{
	float r = 0.0;
	float amp = 0.5;
	for (int o = 0; o < 4; o++)
	{
		r += amp * ldGNoise(x, s + uint(o) * 101U);
		x = x * 2.0 + vec2(17.13, 9.71);
		amp *= 0.5;
	}
	return r * 1.4;
}
// value noise in [0,1]. smoothness 0 = linear (angular kinks), 1 = quintic (smooth)
float ldVNoise(vec2 x, uint s, float smoothness)
{
	ivec2 i = ivec2(floor(x));
	vec2 f = fract(x);
	vec2 q = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
	vec2 u = mix(f, q, smoothness);
	float a = ldHash21(i, s);
	float b = ldHash21(i + ivec2(1, 0), s);
	float c = ldHash21(i + ivec2(0, 1), s);
	float d = ldHash21(i + ivec2(1, 1), s);
	return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
// PIL "L" conversion weights (ITU-R 601), matches linedraw's IM.convert("L")
float ldLuma(vec3 c)
{
	return dot(c, vec3(0.299, 0.587, 0.114));
}

// linedraw :: auto levels (1x1 output)
// Emulates PIL ImageOps.autocontrast(img, cutoff): builds a luminance histogram
// from a grid of samples and finds the low/high cutoff points.
// Input 0 : source image
// Output  : r = low point, g = high point
uniform vec4 uCutoff;   // x = cutoff fraction removed from each end (0.10 = linedraw default)

layout(location = 0) out vec4 fragColor;

#define LD_GRID 48
#define LD_BINS 64

void main()
{
	float hist[LD_BINS];
	for (int i = 0; i < LD_BINS; i++)
		hist[i] = 0.0;

	for (int y = 0; y < LD_GRID; y++)
	{
		for (int x = 0; x < LD_GRID; x++)
		{
			vec2 uv = (vec2(x, y) + 0.5) / float(LD_GRID);
			vec4 c = textureLod(sTD2DInputs[0], uv, 3.0);
			float l = clamp(ldLuma(c.rgb), 0.0, 1.0);
			int b = clamp(int(l * float(LD_BINS)), 0, LD_BINS - 1);
			hist[b] += 1.0;
		}
	}

	float total = float(LD_GRID * LD_GRID);
	float cut = total * clamp(uCutoff.x, 0.0, 0.49);

	int lo = 0;
	float acc = 0.0;
	for (int i = 0; i < LD_BINS; i++)
	{
		acc += hist[i];
		if (acc > cut) { lo = i; break; }
	}
	int hi = LD_BINS - 1;
	acc = 0.0;
	for (int i = LD_BINS - 1; i >= 0; i--)
	{
		acc += hist[i];
		if (acc > cut) { hi = i; break; }
	}

	float l = float(lo) / float(LD_BINS);
	float h = float(hi + 1) / float(LD_BINS);
	if (h - l < 1.0 / float(LD_BINS))
	{
		l = 0.0;
		h = 1.0;
	}
	fragColor = TDOutputSwizzle(vec4(l, h, 0.0, 1.0));
}
'''

SHADERS['prep'] = r'''
// ---------------------------------------------------------------------------
// linedraw common helpers (hashing + noise). Self-contained, no TD noise calls.
// Port of LingDong-/linedraw (MIT) to GLSL by Ro Mayz.
// ---------------------------------------------------------------------------
uint ldHash(uint x)
{
	x ^= x >> 16; x *= 0x7feb352dU;
	x ^= x >> 15; x *= 0x846ca68bU;
	x ^= x >> 16;
	return x;
}
float ldHash21(ivec2 p, uint s)
{
	uint h = ldHash(uint(p.x) * 1597334677U ^ ldHash(uint(p.y) ^ (s * 0x9E3779B9U)));
	return float(h) * (1.0 / 4294967295.0);
}
float ldHash11(float x, uint s)
{
	return ldHash21(ivec2(int(floor(x)), 0), s);
}
vec2 ldGrad(ivec2 p, uint s)
{
	float a = ldHash21(p, s) * 6.28318530718;
	return vec2(cos(a), sin(a));
}
// gradient noise, roughly [-0.7, 0.7]
float ldGNoise(vec2 x, uint s)
{
	ivec2 i = ivec2(floor(x));
	vec2 f = fract(x);
	vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
	float a = dot(ldGrad(i, s), f);
	float b = dot(ldGrad(i + ivec2(1, 0), s), f - vec2(1.0, 0.0));
	float c = dot(ldGrad(i + ivec2(0, 1), s), f - vec2(0.0, 1.0));
	float d = dot(ldGrad(i + ivec2(1, 1), s), f - vec2(1.0, 1.0));
	return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
// 4-octave fbm like p5.js noise(), roughly [-0.5, 0.5]
float ldFbm(vec2 x, uint s)
{
	float r = 0.0;
	float amp = 0.5;
	for (int o = 0; o < 4; o++)
	{
		r += amp * ldGNoise(x, s + uint(o) * 101U);
		x = x * 2.0 + vec2(17.13, 9.71);
		amp *= 0.5;
	}
	return r * 1.4;
}
// value noise in [0,1]. smoothness 0 = linear (angular kinks), 1 = quintic (smooth)
float ldVNoise(vec2 x, uint s, float smoothness)
{
	ivec2 i = ivec2(floor(x));
	vec2 f = fract(x);
	vec2 q = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
	vec2 u = mix(f, q, smoothness);
	float a = ldHash21(i, s);
	float b = ldHash21(i + ivec2(1, 0), s);
	float c = ldHash21(i + ivec2(0, 1), s);
	float d = ldHash21(i + ivec2(1, 1), s);
	return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
// PIL "L" conversion weights (ITU-R 601), matches linedraw's IM.convert("L")
float ldLuma(vec3 c)
{
	return dot(c, vec3(0.299, 0.587, 0.114));
}

// linedraw :: tone prep
// Input 0 : tone image (any TOP / Render TOP beauty pass)
// Input 1 : auto levels (1x1, r = low, g = high)
// Input 2 : G-buffer 0  (view normal xyz, linear depth)   [scene mode]
// Input 3 : G-buffer 1  (hatch coords xy, axis, object id) [scene mode]
// Output  : r = tone (0 black .. 1 white), g = raw luma, b = geometry mask, a = 1
uniform vec4 uLevels;   // autoLevels, blackPoint, whitePoint, gamma
uniform vec4 uTone;     // contrast, brightness, invert, shadeMode (0 image,1 lambert,2 multiply,3 darkest)
uniform vec4 uLight;    // key light direction (view space) xyz, ambient
uniform vec4 uScene;    // sceneMode, hasToneImage, hatchBackground, unused

layout(location = 0) out vec4 fragColor;

ivec2 ldTexel(int idx, vec2 uv)
{
	vec2 res = uTD2DInfos[idx].res.zw;
	return clamp(ivec2(uv * res), ivec2(0), ivec2(res) - 1);
}

void main()
{
	vec4 src = texture(sTD2DInputs[0], vUV.st);
	float luma = ldLuma(src.rgb);
	vec2 lv = texelFetch(sTD2DInputs[1], ivec2(0), 0).rg;

	float t = luma;
	if (uLevels.x > 0.5)
		t = (t - lv.x) / max(lv.y - lv.x, 1e-4);
	t = (t - uLevels.y) / max(uLevels.z - uLevels.y, 1e-4);
	t = clamp(t, 0.0, 1.0);
	t = pow(t, 1.0 / max(uLevels.w, 1e-3));
	t = clamp((t - 0.5) * uTone.x + 0.5 + uTone.y, 0.0, 1.0);
	if (uTone.z > 0.5)
		t = 1.0 - t;

	float mask = 1.0;
	if (uScene.x > 0.5)
	{
		vec4 g0 = texelFetch(sTD2DInputs[2], ldTexel(2, vUV.st), 0);
		vec4 g1 = texelFetch(sTD2DInputs[3], ldTexel(3, vUV.st), 0);
		bool geo = g1.w > 1.5;
		vec3 n = g0.xyz;
		float lam = 1.0;
		if (geo && dot(n, n) > 1e-6)
		{
			n = normalize(n);
			vec3 L = normalize(uLight.xyz + vec3(0.0, 0.0, 1e-5));
			lam = uLight.w + (1.0 - uLight.w) * max(dot(n, L), 0.0);
		}
		int mode = int(uTone.w + 0.5);
		if (uScene.y < 0.5)
			mode = 1;
		if (mode == 1)
			t = lam;
		else if (mode == 2)
			t = t * lam;
		else if (mode == 3)
			t = min(t, lam);
		if (!geo)
		{
			mask = 0.0;
			if (uScene.z < 0.5)
				t = 1.0;
		}
	}
	fragColor = TDOutputSwizzle(vec4(t, luma, mask, 1.0));
}
'''

SHADERS['edges'] = r'''
// ---------------------------------------------------------------------------
// linedraw common helpers (hashing + noise). Self-contained, no TD noise calls.
// Port of LingDong-/linedraw (MIT) to GLSL by Ro Mayz.
// ---------------------------------------------------------------------------
uint ldHash(uint x)
{
	x ^= x >> 16; x *= 0x7feb352dU;
	x ^= x >> 15; x *= 0x846ca68bU;
	x ^= x >> 16;
	return x;
}
float ldHash21(ivec2 p, uint s)
{
	uint h = ldHash(uint(p.x) * 1597334677U ^ ldHash(uint(p.y) ^ (s * 0x9E3779B9U)));
	return float(h) * (1.0 / 4294967295.0);
}
float ldHash11(float x, uint s)
{
	return ldHash21(ivec2(int(floor(x)), 0), s);
}
vec2 ldGrad(ivec2 p, uint s)
{
	float a = ldHash21(p, s) * 6.28318530718;
	return vec2(cos(a), sin(a));
}
// gradient noise, roughly [-0.7, 0.7]
float ldGNoise(vec2 x, uint s)
{
	ivec2 i = ivec2(floor(x));
	vec2 f = fract(x);
	vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
	float a = dot(ldGrad(i, s), f);
	float b = dot(ldGrad(i + ivec2(1, 0), s), f - vec2(1.0, 0.0));
	float c = dot(ldGrad(i + ivec2(0, 1), s), f - vec2(0.0, 1.0));
	float d = dot(ldGrad(i + ivec2(1, 1), s), f - vec2(1.0, 1.0));
	return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
// 4-octave fbm like p5.js noise(), roughly [-0.5, 0.5]
float ldFbm(vec2 x, uint s)
{
	float r = 0.0;
	float amp = 0.5;
	for (int o = 0; o < 4; o++)
	{
		r += amp * ldGNoise(x, s + uint(o) * 101U);
		x = x * 2.0 + vec2(17.13, 9.71);
		amp *= 0.5;
	}
	return r * 1.4;
}
// value noise in [0,1]. smoothness 0 = linear (angular kinks), 1 = quintic (smooth)
float ldVNoise(vec2 x, uint s, float smoothness)
{
	ivec2 i = ivec2(floor(x));
	vec2 f = fract(x);
	vec2 q = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
	vec2 u = mix(f, q, smoothness);
	float a = ldHash21(i, s);
	float b = ldHash21(i + ivec2(1, 0), s);
	float c = ldHash21(i + ivec2(0, 1), s);
	float d = ldHash21(i + ivec2(1, 1), s);
	return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
// PIL "L" conversion weights (ITU-R 601), matches linedraw's IM.convert("L")
float ldLuma(vec3 c)
{
	return dot(c, vec3(0.299, 0.587, 0.114));
}

// linedraw :: edge detection (runs at contour resolution = Design Width / Contour Simplify)
// Image edges : Canny-style (3x3 gaussian -> sobel -> non-max suppression -> double threshold)
// Scene edges : silhouettes / depth breaks, normal creases, object-id changes from the G-buffer
// Input 0 : prep (r = tone)
// Input 1 : G-buffer 0 (view normal xyz, linear depth)
// Input 2 : G-buffer 1 (hatch coords xy, axis, object id)
// Output  : r = class (1 strong, 0.5 weak, 0 none), gb = sub-texel edge position, a = magnitude
uniform vec4 uCanny;    // lowThreshold, highThreshold, imageEdgesOn, unused
uniform vec4 uGeo;      // depthOn, depthThreshold, normalOn, normalAngle (degrees)
uniform vec4 uGeo2;     // idOn, sceneMode, unused, unused

layout(location = 0) out vec4 fragColor;

struct LdG
{
	float w;    // inverse linear depth
	vec3 n;
	float id;
	bool fg;
};

LdG ldLoadG(ivec2 p)
{
	ivec2 res = ivec2(uTD2DInfos[1].res.zw);
	p = clamp(p, ivec2(0), res - 1);
	vec4 g0 = texelFetch(sTD2DInputs[1], p, 0);
	vec4 g1 = texelFetch(sTD2DInputs[2], p, 0);
	LdG s;
	s.fg = g1.w > 1.5 && g0.w > 0.0;
	s.w = s.fg ? 1.0 / g0.w : 0.0;
	s.n = dot(g0.xyz, g0.xyz) > 1e-8 ? normalize(g0.xyz) : vec3(0.0, 0.0, 1.0);
	s.id = g1.w;
	return s;
}

float ldTone(vec2 pc, vec2 oRes, float lod)
{
	return textureLod(sTD2DInputs[0], pc / oRes, lod).r;
}

void main()
{
	vec2 oRes = uTDOutputInfo.res.zw;
	vec2 pc = vUV.st * oRes;

	float cls = 0.0;
	vec2 ofs = vec2(0.0);
	float mag = 0.0;

	// ---------------- scene (G-buffer) edges ----------------
	if (uGeo2.y > 0.5)
	{
		vec2 gRes = uTD2DInfos[1].res.zw;
		int st = max(1, int(gRes.x / oRes.x + 0.5));
		ivec2 g = ivec2(vUV.st * gRes);
		LdG C = ldLoadG(g);
		if (C.fg)
		{
			ivec2 dirs[4] = ivec2[4](ivec2(st, 0), ivec2(-st, 0), ivec2(0, st), ivec2(0, -st));
			LdG N[4];
			for (int i = 0; i < 4; i++)
				N[i] = ldLoadG(g + dirs[i]);
			vec2 acc = vec2(0.0);
			float cnt = 0.0;
			for (int i = 0; i < 4; i++)
			{
				LdG nb = N[i];
				LdG op = N[i ^ 1];
				bool e = false;
				if (!nb.fg)
				{
					e = (uGeo.x > 0.5) || (uGeo2.x > 0.5);
				}
				else
				{
					if (uGeo.x > 0.5)
					{
						// inverse depth is affine across planes in screen space,
						// so a laplacian on it ignores slanted surfaces
						float direct = (C.w - nb.w) / C.w;
						float lap = op.fg ? ((2.0 * C.w - op.w) - nb.w) / C.w : direct;
						if (min(direct, lap) > uGeo.y)
							e = true;
					}
					bool fwd = (i == 0) || (i == 2);
					if (fwd && uGeo.z > 0.5 && dot(C.n, nb.n) < cos(radians(uGeo.w)))
						e = true;
					if (fwd && uGeo2.x > 0.5 && abs(C.id - nb.id) > 0.5)
						e = true;
				}
				if (e)
				{
					acc += vec2(dirs[i]) / float(st) * 0.5;
					cnt += 1.0;
				}
			}
			if (cnt > 0.0)
			{
				cls = 1.0;
				ofs = clamp(acc / cnt, vec2(-0.5), vec2(0.5));
				mag = 1.0;
			}
		}
	}

	// ---------------- image edges (Canny-style) ----------------
	if (cls < 0.5 && uCanny.z > 0.5)
	{
		vec2 tRes = uTD2DInfos[0].res.zw;
		float lod = max(log2(tRes.x / oRes.x), 0.0);

		float T[49];
		for (int j = 0; j < 7; j++)
			for (int i = 0; i < 7; i++)
				T[j * 7 + i] = ldTone(pc + vec2(i - 3, j - 3), oRes, lod);

		// 3x3 gaussian (OpenCV GaussianBlur((3,3),0) == [1 2 1]/4) -> 5x5
		float B[25];
		for (int j = 0; j < 5; j++)
		{
			for (int i = 0; i < 5; i++)
			{
				int c = (j + 1) * 7 + (i + 1);
				float s = 4.0 * T[c]
						+ 2.0 * (T[c - 1] + T[c + 1] + T[c - 7] + T[c + 7])
						+ (T[c - 8] + T[c - 6] + T[c + 6] + T[c + 8]);
				B[j * 5 + i] = s / 16.0;
			}
		}

		// sobel on the inner 3x3
		float M[9];
		vec2 G0 = vec2(0.0);
		for (int j = 0; j < 3; j++)
		{
			for (int i = 0; i < 3; i++)
			{
				int c = (j + 1) * 5 + (i + 1);
				float gx = (B[c - 5 + 1] + 2.0 * B[c + 1] + B[c + 5 + 1])
						 - (B[c - 5 - 1] + 2.0 * B[c - 1] + B[c + 5 - 1]);
				float gy = (B[c + 5 - 1] + 2.0 * B[c + 5] + B[c + 5 + 1])
						 - (B[c - 5 - 1] + 2.0 * B[c - 5] + B[c - 5 + 1]);
				M[j * 3 + i] = length(vec2(gx, gy));
				if (i == 1 && j == 1)
					G0 = vec2(gx, gy);
			}
		}

		float m0 = M[4];
		if (m0 > uCanny.x)
		{
			vec2 d = G0 / max(m0, 1e-6);
			// bilinear lookup of the 3x3 magnitude grid at +-d
			vec2 pp = d + 1.0;
			vec2 pn = -d + 1.0;
			ivec2 ip = clamp(ivec2(floor(pp)), ivec2(0), ivec2(1));
			ivec2 in_ = clamp(ivec2(floor(pn)), ivec2(0), ivec2(1));
			vec2 fp = pp - vec2(ip);
			vec2 fn = pn - vec2(in_);
			float mp = mix(mix(M[ip.y * 3 + ip.x], M[ip.y * 3 + ip.x + 1], fp.x),
						   mix(M[(ip.y + 1) * 3 + ip.x], M[(ip.y + 1) * 3 + ip.x + 1], fp.x), fp.y);
			float mn = mix(mix(M[in_.y * 3 + in_.x], M[in_.y * 3 + in_.x + 1], fn.x),
						   mix(M[(in_.y + 1) * 3 + in_.x], M[(in_.y + 1) * 3 + in_.x + 1], fn.x), fn.y);
			if (m0 >= mp && m0 > mn)
			{
				float den = mn - 2.0 * m0 + mp;
				float s = abs(den) > 1e-6 ? 0.5 * (mn - mp) / den : 0.0;
				ofs = d * clamp(s, -0.5, 0.5);
				cls = m0 > uCanny.y ? 1.0 : 0.5;
				mag = m0;
			}
		}
	}

	fragColor = TDOutputSwizzle(vec4(cls, ofs, mag));
}
'''

SHADERS['hyst'] = r'''
// ---------------------------------------------------------------------------
// linedraw common helpers (hashing + noise). Self-contained, no TD noise calls.
// Port of LingDong-/linedraw (MIT) to GLSL by Ro Mayz.
// ---------------------------------------------------------------------------
uint ldHash(uint x)
{
	x ^= x >> 16; x *= 0x7feb352dU;
	x ^= x >> 15; x *= 0x846ca68bU;
	x ^= x >> 16;
	return x;
}
float ldHash21(ivec2 p, uint s)
{
	uint h = ldHash(uint(p.x) * 1597334677U ^ ldHash(uint(p.y) ^ (s * 0x9E3779B9U)));
	return float(h) * (1.0 / 4294967295.0);
}
float ldHash11(float x, uint s)
{
	return ldHash21(ivec2(int(floor(x)), 0), s);
}
vec2 ldGrad(ivec2 p, uint s)
{
	float a = ldHash21(p, s) * 6.28318530718;
	return vec2(cos(a), sin(a));
}
// gradient noise, roughly [-0.7, 0.7]
float ldGNoise(vec2 x, uint s)
{
	ivec2 i = ivec2(floor(x));
	vec2 f = fract(x);
	vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
	float a = dot(ldGrad(i, s), f);
	float b = dot(ldGrad(i + ivec2(1, 0), s), f - vec2(1.0, 0.0));
	float c = dot(ldGrad(i + ivec2(0, 1), s), f - vec2(0.0, 1.0));
	float d = dot(ldGrad(i + ivec2(1, 1), s), f - vec2(1.0, 1.0));
	return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
// 4-octave fbm like p5.js noise(), roughly [-0.5, 0.5]
float ldFbm(vec2 x, uint s)
{
	float r = 0.0;
	float amp = 0.5;
	for (int o = 0; o < 4; o++)
	{
		r += amp * ldGNoise(x, s + uint(o) * 101U);
		x = x * 2.0 + vec2(17.13, 9.71);
		amp *= 0.5;
	}
	return r * 1.4;
}
// value noise in [0,1]. smoothness 0 = linear (angular kinks), 1 = quintic (smooth)
float ldVNoise(vec2 x, uint s, float smoothness)
{
	ivec2 i = ivec2(floor(x));
	vec2 f = fract(x);
	vec2 q = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
	vec2 u = mix(f, q, smoothness);
	float a = ldHash21(i, s);
	float b = ldHash21(i + ivec2(1, 0), s);
	float c = ldHash21(i + ivec2(0, 1), s);
	float d = ldHash21(i + ivec2(1, 1), s);
	return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
// PIL "L" conversion weights (ITU-R 601), matches linedraw's IM.convert("L")
float ldLuma(vec3 c)
{
	return dot(c, vec3(0.299, 0.587, 0.114));
}

// linedraw :: hysteresis + speck removal (run with Passes = N on the Common page)
// Each pass promotes weak edges touching a strong edge. The last pass drops the
// remaining weak edges and removes isolated specks (like linedraw dropping contours < 4 pts).
// Input 0 : edges (replaced by the previous pass's result after pass 0)
uniform vec4 uHyst;     // passes, minNeighbors, unused, unused

layout(location = 0) out vec4 fragColor;

vec4 ldFetch(ivec2 p)
{
	ivec2 res = ivec2(uTD2DInfos[0].res.zw);
	return texelFetch(sTD2DInputs[0], clamp(p, ivec2(0), res - 1), 0);
}

void main()
{
	ivec2 p = ivec2(vUV.st * uTD2DInfos[0].res.zw);
	vec4 c = ldFetch(p);

	if (c.r > 0.25 && c.r < 0.75)
	{
		for (int j = -1; j <= 1; j++)
			for (int i = -1; i <= 1; i++)
				if ((i != 0 || j != 0) && ldFetch(p + ivec2(i, j)).r > 0.75)
					c.r = 1.0;
	}

	bool last = uTDPass >= int(uHyst.x + 0.5) - 1;
	if (last)
	{
		if (c.r < 0.75)
		{
			c = vec4(0.0);
		}
		else if (uHyst.y > 0.5)
		{
			float n = 0.0;
			for (int j = -2; j <= 2; j++)
				for (int i = -2; i <= 2; i++)
					if ((i != 0 || j != 0) && ldFetch(p + ivec2(i, j)).r > 0.75)
						n += 1.0;
			if (n < uHyst.y)
				c = vec4(0.0);
		}
	}
	fragColor = TDOutputSwizzle(c);
}
'''

SHADERS['chords'] = r'''
// ---------------------------------------------------------------------------
// linedraw common helpers (hashing + noise). Self-contained, no TD noise calls.
// Port of LingDong-/linedraw (MIT) to GLSL by Ro Mayz.
// ---------------------------------------------------------------------------
uint ldHash(uint x)
{
	x ^= x >> 16; x *= 0x7feb352dU;
	x ^= x >> 15; x *= 0x846ca68bU;
	x ^= x >> 16;
	return x;
}
float ldHash21(ivec2 p, uint s)
{
	uint h = ldHash(uint(p.x) * 1597334677U ^ ldHash(uint(p.y) ^ (s * 0x9E3779B9U)));
	return float(h) * (1.0 / 4294967295.0);
}
float ldHash11(float x, uint s)
{
	return ldHash21(ivec2(int(floor(x)), 0), s);
}
vec2 ldGrad(ivec2 p, uint s)
{
	float a = ldHash21(p, s) * 6.28318530718;
	return vec2(cos(a), sin(a));
}
// gradient noise, roughly [-0.7, 0.7]
float ldGNoise(vec2 x, uint s)
{
	ivec2 i = ivec2(floor(x));
	vec2 f = fract(x);
	vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
	float a = dot(ldGrad(i, s), f);
	float b = dot(ldGrad(i + ivec2(1, 0), s), f - vec2(1.0, 0.0));
	float c = dot(ldGrad(i + ivec2(0, 1), s), f - vec2(0.0, 1.0));
	float d = dot(ldGrad(i + ivec2(1, 1), s), f - vec2(1.0, 1.0));
	return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
// 4-octave fbm like p5.js noise(), roughly [-0.5, 0.5]
float ldFbm(vec2 x, uint s)
{
	float r = 0.0;
	float amp = 0.5;
	for (int o = 0; o < 4; o++)
	{
		r += amp * ldGNoise(x, s + uint(o) * 101U);
		x = x * 2.0 + vec2(17.13, 9.71);
		amp *= 0.5;
	}
	return r * 1.4;
}
// value noise in [0,1]. smoothness 0 = linear (angular kinks), 1 = quintic (smooth)
float ldVNoise(vec2 x, uint s, float smoothness)
{
	ivec2 i = ivec2(floor(x));
	vec2 f = fract(x);
	vec2 q = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
	vec2 u = mix(f, q, smoothness);
	float a = ldHash21(i, s);
	float b = ldHash21(i + ivec2(1, 0), s);
	float c = ldHash21(i + ivec2(0, 1), s);
	float d = ldHash21(i + ivec2(1, 1), s);
	return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
// PIL "L" conversion weights (ITU-R 601), matches linedraw's IM.convert("L")
float ldLuma(vec3 c)
{
	return dot(c, vec3(0.299, 0.587, 0.114));
}

// linedraw :: contour chords (one output pixel per N x N block of edge texels)
// linedraw keeps every 8th point of each traced contour, which turns curves into straight
// chords. Here every block looks at where edges cross its border: a block crossed by a single
// curve stores that curve's entry/exit points so the ink pass can draw one straight segment.
// Input 0 : edges after hysteresis
// Output  : rgba = chord (a.xy, b.xy) in edge-texel coords
//           r = -2 -> empty block, r = -1 -> complex block (ink draws the raw edges there)
uniform vec4 uChord;    // block size N (edge texels), unused...

layout(location = 0) out vec4 fragColor;

#define LD_MAXN 16

bool ldE(ivec2 t, ivec2 eRes, out vec2 pos)
{
	pos = vec2(0.0);
	if (any(lessThan(t, ivec2(0))) || any(greaterThanEqual(t, eRes)))
		return false;
	vec4 e = texelFetch(sTD2DInputs[0], t, 0);
	if (e.r < 0.75)
		return false;
	pos = vec2(t) + 0.5 + e.gb;
	return true;
}

ivec2 ldRing(int r, ivec2 o, int N)
{
	if (r < N)
		return ivec2(o.x + r, o.y);
	if (r < 2 * N)
		return ivec2(o.x + N, o.y + (r - N));
	if (r < 3 * N)
		return ivec2(o.x + N - (r - 2 * N), o.y + N);
	return ivec2(o.x, o.y + N - (r - 3 * N));
}

void main()
{
	ivec2 eRes = ivec2(uTD2DInfos[0].res.zw);
	int N = clamp(int(uChord.x + 0.5), 2, LD_MAXN);
	ivec2 cell = ivec2(vUV.st * uTDOutputInfo.res.zw);
	ivec2 o = cell * N;

	int E = 0;
	vec2 tmp;
	for (int j = 0; j <= N; j++)
		for (int i = 0; i <= N; i++)
			if (ldE(o + ivec2(i, j), eRes, tmp))
				E++;
	if (E == 0)
	{
		fragColor = TDOutputSwizzle(vec4(-2.0, 0.0, 0.0, 0.0));
		return;
	}

	int ringN = 4 * N;
	bool on[4 * LD_MAXN];
	vec2 pos[4 * LD_MAXN];
	int start = -1;
	for (int r = 0; r < ringN; r++)
	{
		on[r] = ldE(ldRing(r, o, N), eRes, pos[r]);
		if (!on[r] && start < 0)
			start = r;
	}

	int runs = 0;
	vec2 rp[3];
	rp[0] = vec2(0.0); rp[1] = vec2(0.0); rp[2] = vec2(0.0);
	if (start >= 0)
	{
		vec2 acc = vec2(0.0);
		float cnt = 0.0;
		for (int k = 1; k <= ringN; k++)
		{
			int r = (start + k) % ringN;
			if (on[r])
			{
				acc += pos[r];
				cnt += 1.0;
			}
			else if (cnt > 0.0)
			{
				if (runs < 3)
					rp[runs] = acc / cnt;
				runs++;
				acc = vec2(0.0);
				cnt = 0.0;
			}
		}
	}

	vec4 res = vec4(-1.0, 0.0, 0.0, 0.0);
	if (start >= 0 && runs == 2 && E <= 3 * N)
	{
		res = vec4(rp[0], rp[1]);
	}
	else if (start >= 0 && runs == 1 && E <= 2 * N)
	{
		// curve ends inside the block: chord from the border crossing to the farthest edge texel
		float far = -1.0;
		vec2 fp = rp[0];
		for (int j = 0; j <= N; j++)
		{
			for (int i = 0; i <= N; i++)
			{
				vec2 p;
				if (ldE(o + ivec2(i, j), eRes, p))
				{
					float d = distance(p, rp[0]);
					if (d > far) { far = d; fp = p; }
				}
			}
		}
		if (far > 1.0)
			res = vec4(rp[0], fp);
	}
	fragColor = TDOutputSwizzle(res);
}
'''

SHADERS['ink'] = r'''
// ---------------------------------------------------------------------------
// linedraw common helpers (hashing + noise). Self-contained, no TD noise calls.
// Port of LingDong-/linedraw (MIT) to GLSL by Ro Mayz.
// ---------------------------------------------------------------------------
uint ldHash(uint x)
{
	x ^= x >> 16; x *= 0x7feb352dU;
	x ^= x >> 15; x *= 0x846ca68bU;
	x ^= x >> 16;
	return x;
}
float ldHash21(ivec2 p, uint s)
{
	uint h = ldHash(uint(p.x) * 1597334677U ^ ldHash(uint(p.y) ^ (s * 0x9E3779B9U)));
	return float(h) * (1.0 / 4294967295.0);
}
float ldHash11(float x, uint s)
{
	return ldHash21(ivec2(int(floor(x)), 0), s);
}
vec2 ldGrad(ivec2 p, uint s)
{
	float a = ldHash21(p, s) * 6.28318530718;
	return vec2(cos(a), sin(a));
}
// gradient noise, roughly [-0.7, 0.7]
float ldGNoise(vec2 x, uint s)
{
	ivec2 i = ivec2(floor(x));
	vec2 f = fract(x);
	vec2 u = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
	float a = dot(ldGrad(i, s), f);
	float b = dot(ldGrad(i + ivec2(1, 0), s), f - vec2(1.0, 0.0));
	float c = dot(ldGrad(i + ivec2(0, 1), s), f - vec2(0.0, 1.0));
	float d = dot(ldGrad(i + ivec2(1, 1), s), f - vec2(1.0, 1.0));
	return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
// 4-octave fbm like p5.js noise(), roughly [-0.5, 0.5]
float ldFbm(vec2 x, uint s)
{
	float r = 0.0;
	float amp = 0.5;
	for (int o = 0; o < 4; o++)
	{
		r += amp * ldGNoise(x, s + uint(o) * 101U);
		x = x * 2.0 + vec2(17.13, 9.71);
		amp *= 0.5;
	}
	return r * 1.4;
}
// value noise in [0,1]. smoothness 0 = linear (angular kinks), 1 = quintic (smooth)
float ldVNoise(vec2 x, uint s, float smoothness)
{
	ivec2 i = ivec2(floor(x));
	vec2 f = fract(x);
	vec2 q = f * f * f * (f * (f * 6.0 - 15.0) + 10.0);
	vec2 u = mix(f, q, smoothness);
	float a = ldHash21(i, s);
	float b = ldHash21(i + ivec2(1, 0), s);
	float c = ldHash21(i + ivec2(0, 1), s);
	float d = ldHash21(i + ivec2(1, 1), s);
	return mix(mix(a, b, u.x), mix(c, d, u.x), u.y);
}
// PIL "L" conversion weights (ITU-R 601), matches linedraw's IM.convert("L")
float ldLuma(vec3 c)
{
	return dot(c, vec3(0.299, 0.587, 0.114));
}

// linedraw :: ink (hatching + contours + composite)
// All sizes are in "design pixels": 1 unit = 1 px of an image Design Width wide (linedraw used 1024),
// so the look stays the same at any output resolution.
// Input 0 : prep  (r = tone, b = geometry mask)        -- mipmapped
// Input 1 : edges (r = class, gb = sub-texel offset)   -- after hysteresis
// Input 2 : chords (per block straight contour segments)
// Input 3 : G-buffer 0 (view normal xyz, linear depth)
// Input 4 : G-buffer 1 (triplanar hatch coords xy, axis, object id)
// Input 5 : G-buffer 2 (uv xy)
uniform vec4 uGlobal;   // designWidth, seed, softness (px), outputMode
uniform vec4 uInk;      // ink color rgba
uniform vec4 uPaper;    // paper color rgba
uniform vec4 uHatch;    // amount, hatchSize, hatchWeight, hatchSpace (0 screen, 1 surface, 2 uv)
uniform vec4 uHatch2;   // cellQuantize, wobble, wobbleFreq, weightVariation
uniform vec4 uHatch3;   // gaps, surfaceSpacing, grain, sceneMode
uniform vec4 uHatch4;   // surfaceLOD, lodDensity, clipToGeometry, unused
uniform vec4 uL1;       // threshold (<0 = off), angle (deg), phase, spacing multiplier
uniform vec4 uL2;
uniform vec4 uL3;
uniform vec4 uL4;
uniform vec4 uCont;     // amount, weight, sketchPasses, angularity
uniform vec4 uCont2;    // displacement, displacementFreq, jitter, jitterFreq
uniform vec4 uCont3;    // style (0 smooth, 1 angular chords), chord block size, unused, unused

layout(location = 0) out vec4 fragColor;

vec2 gORes;     // output resolution (px)
float gK;       // output px per design unit
uint gSeed;
float gSoft;
float gToneLod; // tone smoothing for hatching (about one stroke width)

float ldToneAt(vec2 pcq)
{
	return textureLod(sTD2DInputs[0], pcq / gORes, gToneLod).r;
}

// tone averaged over the axis-aligned hatch cell containing designPos
// (linedraw samples the image downsized to resolution / hatch_size)
float ldToneCell(vec2 designPos, float cell)
{
	vec2 cc = (floor(designPos / cell) + 0.5) * cell;
	float texelsPerCell = cell * gK * (uTD2DInfos[0].res.z / gORes.x);
	float lod = max(log2(max(texelsPerCell, 1.0)), 0.0);
	return textureLod(sTD2DInputs[0], cc * gK / gORes, lod).r;
}

// One family of parallel wobbly lines.
// q  : pattern coordinate (design units in screen mode)
// J  : dq/dpc (column 0 = dq/dx, column 1 = dq/dy)
float ldHatchLayer(vec2 q, mat2 J, vec2 pc, vec4 L, int li, bool screen)
{
	if (L.x < 0.0)
		return 0.0;
	float S = uHatch.y * max(L.w, 0.05);
	float a = radians(L.y);
	vec2 dir = vec2(cos(a), sin(a));
	vec2 nrm = vec2(-dir.y, dir.x);
	float u = dot(q, dir);
	float v = dot(q, nrm);
	vec2 gV = transpose(J) * nrm;
	float gv2 = max(dot(gV, gV), 1e-12);
	float invG = inversesqrt(gv2);

	// surface LOD: keep the on-screen line spacing near Hatch Size by dropping / adding
	// every other line (odd lines of the current level fade out), so grazing or distant
	// surfaces don't turn into solid black and close-ups don't go sparse.
	float lvl = 0.0;
	if (!screen && uHatch4.x > 0.5)
		lvl = clamp(log2(max(sqrt(gv2) * gK / max(uHatch4.y, 0.05), 1e-6)), -6.0, 12.0);
	float L0 = floor(lvl);
	float f = lvl - L0;
	float sc = exp2(L0);
	float Sp = S * sc;
	int nC = clamp(int(0.7 * uHatch2.y * S / Sp + 0.6), 1, 4);

	float wl0 = uHatch.z * gK;
	float k0 = floor((v / S - L.z) / sc + 0.5);
	float x = u / S;
	uint ls = gSeed + uint(li) * 1013U;
	float cov = 0.0;
	for (int j = -nC; j <= nC; j++)
	{
		float kk = k0 + float(j);
		float fade = mod(kk, 2.0) > 0.5 ? 1.0 - f : 1.0;
		if (fade < 0.002)
			continue;
		float kAbs = kk * sc;      // level-independent line id
		// per-line wobble: linedraw used perlin.noise(i*0.5, j*0.1) * hatch_size
		float w = uHatch2.y > 0.0 ? uHatch2.y * S * ldFbm(vec2(kAbs * 0.5 + float(li) * 7.31, x * 0.1 * uHatch2.z), ls) : 0.0;
		float vc = (kAbs + L.z) * S + w;
		float dq = v - vc;
		float dpx = abs(dq) * invG;
		float wl = wl0;
		if (uHatch2.w > 0.0)
			wl *= max(0.0, 1.0 + uHatch2.w * 2.0 * ldFbm(vec2(x * 0.15, kAbs * 1.7 + 50.0), ls + 7U));
		if (dpx > wl * 0.5 + gSoft)
			continue;
		if (uHatch3.x > 0.0)
		{
			float g = ldVNoise(vec2(x * 0.35, kAbs * 3.1), ls + 11U, 1.0);
			if (g < uHatch3.x)
				continue;
		}
		// tone measured on the line centre -> constant stroke width, segments end cleanly
		vec2 cpc = pc - dq * gV / gv2;
		float t = ldToneAt(cpc);
		if (screen && uHatch2.x > 0.0)
			t = mix(t, ldToneCell(q - dq * nrm, uHatch.y), uHatch2.x);
		if (t >= L.x)
			continue;
		cov = max(cov, fade * clamp((wl * 0.5 - dpx) / gSoft + 0.5, 0.0, 1.0));
	}
	return cov;
}

float ldHatchAll(vec2 q, mat2 J, vec2 pc, bool screen)
{
	float c = 0.0;
	c = max(c, ldHatchLayer(q, J, pc, uL1, 0, screen));
	c = max(c, ldHatchLayer(q, J, pc, uL2, 1, screen));
	c = max(c, ldHatchLayer(q, J, pc, uL3, 2, screen));
	c = max(c, ldHatchLayer(q, J, pc, uL4, 3, screen));
	return c;
}

// ---- surface-locked hatch coordinates from the G-buffer -------------------
vec4 ldG(int which, ivec2 p)
{
	ivec2 res = ivec2(uTD2DInfos[4].res.zw);
	p = clamp(p, ivec2(0), res - 1);
	if (which == 1)
		return texelFetch(sTD2DInputs[4], p, 0);
	return texelFetch(sTD2DInputs[5], p, 0);
}

// returns false if the pixel has no usable surface frame
bool ldSurfaceFrame(int which, out vec2 q, out mat2 J)
{
	vec2 gRes = uTD2DInfos[4].res.zw;
	vec2 gc = vUV.st * gRes;
	ivec2 gi = clamp(ivec2(gc), ivec2(0), ivec2(gRes) - 1);
	vec4 c1 = ldG(1, gi);
	q = vec2(0.0);
	J = mat2(0.0);
	if (c1.w < 1.5)
		return false;
	float sq = uHatch.y / max(uHatch3.y, 1e-6);
	vec2 c = ldG(which, gi).xy * sq;
	vec2 d[2];
	ivec2 ax[2] = ivec2[2](ivec2(1, 0), ivec2(0, 1));
	for (int a = 0; a < 2; a++)
	{
		vec4 f1 = ldG(1, gi + ax[a]);
		vec4 b1 = ldG(1, gi - ax[a]);
		bool fv = abs(f1.w - c1.w) < 0.5 && abs(f1.z - c1.z) < 0.5;
		bool bv = abs(b1.w - c1.w) < 0.5 && abs(b1.z - c1.z) < 0.5;
		vec2 fd = ldG(which, gi + ax[a]).xy * sq - c;
		vec2 bd = c - ldG(which, gi - ax[a]).xy * sq;
		if (fv && bv)
			d[a] = dot(fd, fd) < dot(bd, bd) ? fd : bd;
		else if (fv)
			d[a] = fd;
		else if (bv)
			d[a] = bd;
		else
			return false;
	}
	mat2 Jg = mat2(d[0], d[1]);
	if (abs(determinant(Jg)) < 1e-10)
		return false;
	q = c + Jg * (gc - (vec2(gi) + 0.5));
	J = Jg * (gRes.x / gORes.x);
	return true;
}

// ---- contours ---------------------------------------------------------------
float ldSegDist(vec2 p, vec2 a, vec2 b)
{
	vec2 pa = p - a;
	vec2 ba = b - a;
	float h = clamp(dot(pa, ba) / max(dot(ba, ba), 1e-8), 0.0, 1.0);
	return length(pa - ba * h);
}

bool ldEdgeAt(ivec2 t, ivec2 eRes, out vec2 pos)
{
	pos = vec2(0.0);
	if (any(lessThan(t, ivec2(0))) || any(greaterThanEqual(t, eRes)))
		return false;
	vec4 e = texelFetch(sTD2DInputs[1], t, 0);
	if (e.r < 0.75)
		return false;
	pos = vec2(t) + 0.5 + e.gb;
	return true;
}

float ldContours(vec2 pc)
{
	ivec2 eRes = ivec2(uTD2DInfos[1].res.zw);
	float e2o = gORes.x / float(eRes.x);
	float halfW = uCont.y * gK * 0.5;
	int R = clamp(int(ceil((halfW + gSoft) / e2o)) + 1, 1, 6);
	int passes = clamp(int(uCont.z + 0.5), 1, 4);
	vec2 p = pc / gK;
	float smoothness = 1.0 - clamp(uCont.w, 0.0, 1.0);
	int style = int(uCont3.x + 0.5);
	int N = clamp(int(uCont3.y + 0.5), 2, 16);
	ivec2 cRes = ivec2(uTD2DInfos[2].res.zw);
	int Rb = clamp((R + N - 1) / N, 1, 3);
	float cov = 0.0;
	for (int ps = 0; ps < passes; ps++)
	{
		uint s = gSeed + uint(ps) * 7777U + 3U;
		float dF = uCont2.y / 160.0;
		vec2 disp = uCont2.x * 2.0 * vec2(ldFbm(p * dF, s), ldFbm(p * dF + 31.7, s + 1U));
		float jF = uCont2.w / 16.0;
		vec2 jit = uCont2.z * 2.0 * (vec2(ldVNoise(p * jF, s + 2U, smoothness),
										  ldVNoise(p * jF + 7.3, s + 3U, smoothness)) - 0.5);
		vec2 qe = (pc + (disp + jit) * gK) / e2o;
		ivec2 base = ivec2(floor(qe));
		float best = 1e9;

		// straight chords from the chord pass (angular style)
		ivec2 cq = ivec2(floor(qe / float(N)));
		int kind[49];   // per nearby block: 0 empty, 1 chord, 2 complex (draw raw edges)
		for (int bj = -Rb; bj <= Rb; bj++)
		{
			for (int bi = -Rb; bi <= Rb; bi++)
			{
				ivec2 cb = cq + ivec2(bi, bj);
				int kd = 0;
				if (all(greaterThanEqual(cb, ivec2(0))) && all(lessThan(cb, cRes)))
				{
					vec4 ch = texelFetch(sTD2DInputs[2], cb, 0);
					if (ch.x < -1.5)
						kd = 0;
					else if (ch.x < -0.5 || style == 0)
						kd = 2;
					else
					{
						kd = 1;
						best = min(best, ldSegDist(qe, ch.xy, ch.zw));
					}
				}
				kind[(bj + 3) * 7 + (bi + 3)] = kd;
			}
		}

		// raw edge polyline (smooth style, or blocks too busy for a single chord)
		for (int j = -R; j <= R; j++)
		{
			for (int i = -R; i <= R; i++)
			{
				ivec2 t = base + ivec2(i, j);
				vec2 a;
				if (!ldEdgeAt(t, eRes, a))
					continue;
				ivec2 rb = t / N - cq;
				if (all(lessThanEqual(abs(rb), ivec2(Rb))) && kind[(rb.y + 3) * 7 + (rb.x + 3)] == 1)
					continue;
				float d = length(qe - a);
				vec2 b, o1;
				bool hx = ldEdgeAt(t + ivec2(1, 0), eRes, b);
				if (hx) d = min(d, ldSegDist(qe, a, b));
				bool hy = ldEdgeAt(t + ivec2(0, 1), eRes, b);
				if (hy) d = min(d, ldSegDist(qe, a, b));
				if (!hx && !hy && ldEdgeAt(t + ivec2(1, 1), eRes, b))
					d = min(d, ldSegDist(qe, a, b));
				if (!hy && !ldEdgeAt(t + ivec2(-1, 0), eRes, o1) && ldEdgeAt(t + ivec2(-1, 1), eRes, b))
					d = min(d, ldSegDist(qe, a, b));
				best = min(best, d);
			}
		}
		cov = max(cov, clamp((halfW - best * e2o) / gSoft + 0.5, 0.0, 1.0));
	}
	return cov;
}

vec3 ldIdColor(float id)
{
	uint h = ldHash(uint(id));
	return vec3(float(h & 255U), float((h >> 8) & 255U), float((h >> 16) & 255U)) / 255.0;
}

void main()
{
	gORes = uTDOutputInfo.res.zw;
	vec2 pc = vUV.st * gORes;
	gK = gORes.x / max(uGlobal.x, 1.0);
	gSeed = uint(int(floor(uGlobal.y))) * 7919U + 13U;
	gSoft = max(uGlobal.z, 0.05);
	gToneLod = max(log2(max(2.0 * uHatch.z * gK * uTD2DInfos[0].res.z / gORes.x, 1.0)), 0.0);
	int mode = int(uGlobal.w + 0.5);
	bool scene = uHatch3.w > 0.5;

	vec4 prep = textureLod(sTD2DInputs[0], vUV.st, 0.0);

	// ---------- hatching ----------
	float hatch = 0.0;
	vec2 hq = pc / gK;
	if (uHatch.x > 0.0)
	{
		int space = scene ? int(uHatch.w + 0.5) : 0;
		bool screen = true;
		mat2 J = mat2(1.0 / gK);
		vec2 q = hq;
		if (space > 0)
		{
			vec2 sq;
			mat2 sJ;
			if (ldSurfaceFrame(space == 1 ? 1 : 2, sq, sJ))
			{
				q = sq;
				J = sJ;
				screen = false;
				hq = sq;
			}
			else if (prep.b > 0.5)
			{
				// geometry pixel without a usable frame (degenerate uv etc.)
				q = vec2(1e5);
			}
		}
		if (q.x < 1e4)
			hatch = ldHatchAll(q, J, pc, screen) * uHatch.x;
		if (scene && uHatch4.z > 0.5)
			hatch *= textureLod(sTD2DInputs[0], vUV.st, 0.0).b;   // keep cell-spill off the background
	}

	// ---------- contours ----------
	float cont = 0.0;
	if (uCont.x > 0.0)
		cont = ldContours(pc) * uCont.x;

	float ink = 1.0 - (1.0 - hatch) * (1.0 - cont);
	if (uHatch3.z > 0.0)
	{
		float g = ldVNoise(pc * 0.35, gSeed + 99U, 1.0) * 0.6 + ldVNoise(pc * 1.3, gSeed + 98U, 1.0) * 0.4;
		ink *= 1.0 - uHatch3.z * smoothstep(0.35, 0.8, g);
	}

	float ia = ink * uInk.a;
	vec4 outc;
	if (mode == 0)
	{
		// premultiplied ink over paper
		vec4 paper = vec4(uPaper.rgb * uPaper.a, uPaper.a);
		outc = vec4(uInk.rgb * ia, ia) + paper * (1.0 - ia);
	}
	else if (mode == 1)
	{
		outc = vec4(uInk.rgb * ia, ia);
	}
	else if (mode == 2)
	{
		outc = vec4(cont, hatch, prep.r, 1.0);
	}
	else if (mode == 3)
	{
		outc = vec4(vec3(prep.r), 1.0);
	}
	else if (mode == 4)
	{
		vec4 e = texture(sTD2DInputs[1], vUV.st);
		outc = vec4(vec3(e.r), 1.0);
	}
	else if (mode == 5)
	{
		vec4 g0 = texelFetch(sTD2DInputs[3], clamp(ivec2(vUV.st * uTD2DInfos[3].res.zw), ivec2(0), ivec2(uTD2DInfos[3].res.zw) - 1), 0);
		outc = vec4(g0.xyz * 0.5 + 0.5, 1.0);
	}
	else if (mode == 6)
	{
		vec4 g0 = texelFetch(sTD2DInputs[3], clamp(ivec2(vUV.st * uTD2DInfos[3].res.zw), ivec2(0), ivec2(uTD2DInfos[3].res.zw) - 1), 0);
		outc = vec4(vec3(g0.w > 0.0 ? exp(-0.15 * g0.w) : 0.0), 1.0);
	}
	else if (mode == 7)
	{
		vec4 g1 = texelFetch(sTD2DInputs[4], clamp(ivec2(vUV.st * uTD2DInfos[4].res.zw), ivec2(0), ivec2(uTD2DInfos[4].res.zw) - 1), 0);
		outc = vec4(g1.w > 1.5 ? ldIdColor(g1.w) : vec3(0.0), 1.0);
	}
	else
	{
		vec2 f = fract(hq / max(uHatch.y, 1e-3));
		outc = vec4(f, 0.0, 1.0);
	}
	fragColor = TDOutputSwizzle(outc);
}
'''

SHADERS['gbuffer_vert'] = r'''
// linedraw :: G-buffer material (vertex). Used as the Override Material of the internal Render TOP.
uniform vec4 uGB;   // x: hatch space for triplanar coords (0 = object/SOP space, 1 = world space)

out Vertex
{
	vec3 camPos;
	vec3 worldNorm;
	vec3 hatchPos;
	vec3 hatchNorm;
	vec2 uv;
	flat float id;
	flat int cameraIndex;
} oVert;

void main()
{
	vec3 P = TDPos();
	vec3 N = TDNormal();
	vec4 worldPos = TDDeform(P);
	vec3 worldNorm = TDDeformNorm(N);
	int ci = TDCameraIndex();

	oVert.camPos = (uTDMats[ci].cam * worldPos).xyz;
	oVert.worldNorm = worldNorm;
	if (uGB.x < 0.5)
	{
		oVert.hatchPos = P;
		oVert.hatchNorm = N;
	}
	else
	{
		oVert.hatchPos = worldPos.xyz;
		oVert.hatchNorm = worldNorm;
	}
	oVert.uv = TDTexCoord(0u).xy;

	// pseudo object id: hash of the Geometry COMP's world matrix + instance id
	mat4 W = uTDMats[ci].world;
	vec4 h = W[3] * 1.0 + W[0] * 1.31 + W[1] * 2.17 + W[2] * 3.07;
	float r = fract(sin(dot(h, vec4(12.9898, 78.233, 37.719, 4.581)) + float(TDInstanceID()) * 0.6180339) * 43758.5453);
	oVert.id = 2.0 + floor(r * 60000.0);
	oVert.cameraIndex = ci;

	gl_Position = TDWorldToProj(worldPos);
}
'''

SHADERS['gbuffer_frag'] = r'''
// linedraw :: G-buffer material (pixel). Writes 3 colour buffers (Render TOP: # of Color Buffers = 3, 32-bit float).
//   buffer 0 : view-space normal xyz, linear depth
//   buffer 1 : triplanar hatch coords xy, dominant axis (0/1/2), object id (>= 2, background = 0)
//   buffer 2 : uv xy
uniform vec4 uGB;

in Vertex
{
	vec3 camPos;
	vec3 worldNorm;
	vec3 hatchPos;
	vec3 hatchNorm;
	vec2 uv;
	flat float id;
	flat int cameraIndex;
} iVert;

layout(location = 0) out vec4 oFragColor[TD_NUM_COLOR_BUFFERS];

void main()
{
	TDCheckDiscard();
	vec3 p = iVert.camPos;
	vec3 hp = iVert.hatchPos;
	// derivatives taken in uniform control flow; used when geometry has no normals
	vec3 faceN = cross(dFdx(p), dFdy(p));
	vec3 faceH = cross(dFdx(hp), dFdy(hp));

	vec3 vn = uTDMats[iVert.cameraIndex].camForNormals * iVert.worldNorm;
	if (dot(vn, vn) < 1e-10)
		vn = faceN;
	vn = normalize(vn);
	if (!TDFrontFacing(p, vn))
		vn = -vn;

	vec3 hn = iVert.hatchNorm;
	if (dot(hn, hn) < 1e-10)
		hn = faceH;
	vec3 an = abs(hn);
	vec2 tri;
	float axis;
	if (an.x >= an.y && an.x >= an.z)
	{
		tri = hp.zy;
		axis = 0.0;
	}
	else if (an.y >= an.z)
	{
		tri = hp.xz;
		axis = 1.0;
	}
	else
	{
		tri = hp.xy;
		axis = 2.0;
	}

	oFragColor[0] = TDOutputSwizzle(vec4(vn, -p.z));
#if TD_NUM_COLOR_BUFFERS > 1
	oFragColor[1] = TDOutputSwizzle(vec4(tri, axis, iVert.id));
#endif
#if TD_NUM_COLOR_BUFFERS > 2
	oFragColor[2] = TDOutputSwizzle(vec4(iVert.uv, 0.0, 1.0));
#endif
}
'''


LD_UTIL = r'''
# helpers used by expressions inside the linedraw component
def _rt(comp):
	try:
		return comp.par.Rendertop.eval()
	except Exception:
		return None

def rtpath(comp):
	r = _rt(comp)
	return r.path if r else ''

def camera(comp):
	c = comp.par.Camera.eval()
	if c:
		return c.path
	r = _rt(comp)
	if r:
		cams = r.par.camera.evalOPs()
		if cams:
			return cams[0].path
	return ''

def geometry(comp):
	g = comp.par.Geometry.eval().strip()
	if g:
		return ' '.join(o.path for o in comp.parent().ops(*g.split()))
	r = _rt(comp)
	if r:
		return ' '.join(o.path for o in r.par.geometry.evalOPs())
	return ''

def res(comp):
	r = _rt(comp)
	if r:
		return (r.width, r.height)
	i = comp.op('in1')
	if i is not None and i.inputs:
		return (i.width, i.height)
	return (1280, 720)

def tonesrc(comp):
	if comp.par.Source.eval() != 'scene':
		return 0
	return {'render': 1, 'input': 0, 'none': 2}.get(comp.par.Toneimage.eval(), 1)
'''

P = 'parent().par.'


def _pars(pg):
	if hasattr(pg, 'pars'):
		try:
			return list(pg.pars())
		except Exception:
			pass
	try:
		return list(pg)
	except Exception:
		return [pg]


def _setup(pars, default=None, lo=None, hi=None, clamp=(False, False), help=None):
	if default is not None and not isinstance(default, (list, tuple)):
		default = [default] * len(pars)
	for i, p in enumerate(pars):
		if lo is not None:
			p.normMin = lo
			p.min = lo
		if hi is not None:
			p.normMax = hi
			p.max = hi
		p.clampMin, p.clampMax = clamp
		if default is not None:
			p.default = default[i]
			p.val = default[i]
		if help:
			try:
				p.help = help
			except Exception:
				pass
	return pars


class _Page:
	def __init__(self, comp, name):
		self.pg = comp.appendCustomPage(name)

	def header(self, label):
		try:
			self.pg.appendHeader('H' + ''.join(c for c in label.lower() if c.isalnum())[:20], label=label)
		except Exception:
			pass

	def float(self, name, label, default, lo=0.0, hi=1.0, clamp=(False, False), help=None, size=1):
		return _setup(_pars(self.pg.appendFloat(name, label=label, size=size)), default, lo, hi, clamp, help)

	def int(self, name, label, default, lo=0, hi=10, clamp=(False, False), help=None, size=1):
		return _setup(_pars(self.pg.appendInt(name, label=label, size=size)), default, lo, hi, clamp, help)

	def toggle(self, name, label, default, help=None):
		return _setup(_pars(self.pg.appendToggle(name, label=label)), bool(default), help=help)

	def menu(self, name, label, names, labels, default, help=None):
		ps = _pars(self.pg.appendMenu(name, label=label))
		for p in ps:
			p.menuNames = names
			p.menuLabels = labels
		return _setup(ps, default, help=help)

	def top(self, name, label, help=None):
		return _setup(_pars(self.pg.appendTOP(name, label=label)), help=help)

	def comp(self, name, label, help=None):
		return _setup(_pars(self.pg.appendCOMP(name, label=label)), help=help)

	def str(self, name, label, default='', help=None):
		return _setup(_pars(self.pg.appendStr(name, label=label)), default, help=help)

	def rgba(self, name, label, default, help=None):
		return _setup(_pars(self.pg.appendRGBA(name, label=label)), list(default), 0.0, 1.0, help=help)

	def xyz(self, name, label, default, lo=-1.0, hi=1.0, help=None):
		return _setup(_pars(self.pg.appendXYZ(name, label=label)), list(default), lo, hi, help=help)


def _add_params(comp):
	pg = _Page(comp, 'Linedraw')
	pg.header('Source')
	pg.menu('Source', 'Source', ['image', 'scene'], ['Image (input TOP)', 'Scene (Render TOP)'], 'image',
			help='Image: draw any TOP wired into the component. Scene: also read depth/normals/ids from a 3D render.')
	pg.top('Rendertop', 'Render TOP', help='Scene mode: the Render TOP to follow. Camera, geometry and resolution are copied from it.')
	pg.comp('Camera', 'Camera (override)', help='Optional. Use this camera instead of the Render TOP\'s.')
	pg.str('Geometry', 'Geometry (override)', '', help='Optional. Geometry COMP names/patterns (relative to the component\'s parent).')
	pg.menu('Toneimage', 'Tone Image', ['render', 'input', 'none'], ['Render TOP', 'Component Input', 'None (shading only)'], 'render',
			help='Scene mode: which image drives hatching density.')
	pg.header('Output')
	pg.menu('Output', 'Output', ['composite', 'ink', 'channels', 'tone', 'edges', 'normals', 'depth', 'ids', 'hatchcoords'],
			['Ink on Paper', 'Ink Only (alpha)', 'Channels (R contour, G hatch, B tone)', 'Debug: Tone', 'Debug: Edges',
			 'Debug: Normals', 'Debug: Depth', 'Debug: Object IDs', 'Debug: Hatch Coords'], 'composite')
	pg.menu('Outputres', 'Output Resolution', ['input', 'custom'], ['Use Input', 'Custom'], 'input',
			help='Lines are drawn analytically, so you can render crisp lines at a higher resolution than the source.')
	pg.int('Resolution', 'Resolution', [1920, 1080], 16, 8192, (True, False), size=2)
	pg.float('Designwidth', 'Design Width', 1024.0, 256.0, 4096.0, (True, False),
			 help='All sizes are in pixels of an image this wide (linedraw used 1024). Keeps the look identical at any resolution.')
	pg.float('Softness', 'Antialias Width', 1.0, 0.25, 3.0, (True, False))
	pg.int('Seed', 'Seed', 0, 0, 100)
	pg.float('Boilrate', 'Boil Rate (fps)', 0.0, 0.0, 24.0, (True, False),
			 help='Re-randomise the wobble N times per second, like hand-drawn animation "boil". 0 = static.')

	pg = _Page(comp, 'Tone')
	pg.toggle('Autolevels', 'Auto Levels', 1, help='PIL autocontrast like linedraw (cuts Auto Cutoff from each end of the histogram).')
	pg.float('Cutoff', 'Auto Cutoff', 0.10, 0.0, 0.3, (True, True))
	pg.float('Blackpoint', 'Black Point', 0.0)
	pg.float('Whitepoint', 'White Point', 1.0)
	pg.float('Gamma', 'Gamma', 1.0, 0.2, 3.0, (True, False))
	pg.float('Contrast', 'Contrast', 1.0, 0.0, 3.0)
	pg.float('Brightness', 'Brightness', 0.0, -0.5, 0.5)
	pg.toggle('Invert', 'Invert', 0)
	pg.header('Scene Shading')
	pg.menu('Shademode', 'Tone From', ['image', 'lambert', 'multiply', 'darkest'],
			['Tone Image', 'Key Light (normals)', 'Image x Key Light', 'Darkest of Both'], 'image',
			help='Scene mode: hatch from the rendered image, from a virtual key light on the normals, or both.')
	pg.xyz('Lightdir', 'Key Light Dir (view)', (-0.5, 0.6, 0.6))
	pg.float('Ambient', 'Ambient', 0.15)
	pg.toggle('Hatchbg', 'Hatch Background', 0, help='Scene mode: also hatch pixels where there is no geometry.')
	pg.toggle('Cliptogeo', 'Clip Hatch to Geometry', 1, help='Scene mode: stop hatch cells spilling past silhouettes.')

	pg = _Page(comp, 'Hatch')
	pg.toggle('Hatch', 'Draw Hatching', 1)
	pg.float('Hatchopacity', 'Hatch Opacity', 1.0)
	pg.float('Hatchsize', 'Hatch Size', 16.0, 4.0, 64.0, (True, False), help='Line spacing / cell size (linedraw --hatch_size).')
	pg.float('Hatchweight', 'Hatch Weight', 1.5, 0.25, 6.0, (True, False))
	pg.float('Cellquant', 'Cell Quantize', 1.0, help='1 = segments start/stop on the hatch grid like linedraw, 0 = smooth.')
	pg.float('Wobble', 'Wobble', 1.0, 0.0, 3.0, (True, False))
	pg.float('Wobblefreq', 'Wobble Freq', 1.0, 0.0, 4.0, (True, False))
	pg.float('Weightvar', 'Weight Variation', 0.0, help='Pen pressure variation along each line.')
	pg.float('Gaps', 'Gaps', 0.0, help='Random breaks along lines (pen skipping).')
	pg.header('Surface Hatching (Scene)')
	pg.menu('Hatchspace', 'Hatch Space', ['screen', 'surface', 'uv'], ['Screen (classic)', 'Surface (triplanar)', 'Geometry UVs'], 'screen',
			help='Scene mode: Surface/UV lock the hatching to the objects so it moves with them instead of swimming.')
	pg.menu('Gbufspace', 'Triplanar Space', ['object', 'world'], ['Object (SOP)', 'World'], 'object')
	pg.float('Surfacespacing', 'Surface Spacing', 0.05, 0.001, 1.0, (True, False), help='Surface mode: world/object units between lines.')
	pg.float('Uvspacing', 'UV Spacing', 0.02, 0.001, 0.25, (True, False), help='UV mode: uv units between lines.')
	pg.toggle('Surfacelod', 'Surface LOD', 1, help='Fade lines in/out so on-screen spacing stays near Hatch Size.')
	pg.float('Loddensity', 'LOD Density', 1.0, 0.25, 4.0, (True, False))
	defaults = [
		(1, 0.565, 3.6, 0.25, 1.0),
		(1, 0.251, 43.2, 0.0, 0.7071),
		(1, 0.063, 3.6, 0.75, 1.0),
		(0, 0.12, -46.0, 0.5, 0.7071),
	]
	for i, (on, th, ang, ph, sp) in enumerate(defaults, 1):
		pg.header('Layer %d' % i)
		pg.toggle('L%don' % i, 'Layer %d' % i, on)
		pg.float('L%dthresh' % i, 'L%d Threshold' % i, th, help='Lines are drawn where tone is below this.')
		pg.float('L%dangle' % i, 'L%d Angle' % i, ang, -90.0, 90.0)
		pg.float('L%dphase' % i, 'L%d Phase' % i, ph)
		pg.float('L%dspacing' % i, 'L%d Spacing x' % i, sp, 0.25, 2.0, (True, False))

	pg = _Page(comp, 'Contours')
	pg.toggle('Contours', 'Draw Contours', 1)
	pg.float('Contouropacity', 'Contour Opacity', 1.0)
	pg.float('Contourweight', 'Contour Weight', 1.5, 0.25, 6.0, (True, False))
	pg.menu('Contourstyle', 'Contour Style', ['smooth', 'angular'], ['Smooth', 'Angular (chords)'], 'angular',
			help='Angular replaces curves with straight chords every Chord Length, like linedraw\'s point skipping.')
	pg.int('Chordlength', 'Chord Length', 8, 2, 16, (True, True))
	pg.int('Contoursimplify', 'Contour Simplify', 2, 1, 4, (True, False), help='Edge map resolution = Design Width / this (linedraw --contour_simplify).')
	pg.header('Image Edges')
	pg.toggle('Imageedges', 'Image Edges', 1)
	pg.float('Lowthresh', 'Low Threshold', 0.3, 0.0, 2.0, (True, False))
	pg.float('Highthresh', 'High Threshold', 0.6, 0.0, 2.0, (True, False))
	pg.int('Hysteresis', 'Hysteresis Passes', 4, 1, 16, (True, False))
	pg.int('Specks', 'Speck Removal', 2, 0, 8, (True, True))
	pg.header('Scene Edges')
	pg.toggle('Depthedges', 'Silhouettes / Depth', 1)
	pg.float('Depththresh', 'Depth Threshold', 0.04, 0.001, 0.5, (True, False))
	pg.toggle('Normaledges', 'Creases (Normals)', 1)
	pg.float('Normalangle', 'Crease Angle', 40.0, 1.0, 90.0, (True, True))
	pg.toggle('Idedges', 'Object Boundaries', 1)
	pg.header('Sketchiness')
	pg.int('Sketchpasses', 'Sketch Passes', 2, 1, 4, (True, True), help='Redraw contours N times with different jitter (linedraw traced each edge twice).')
	pg.float('Displace', 'Displacement', 2.5, 0.0, 20.0, (True, False))
	pg.float('Displacefreq', 'Displacement Freq', 1.0, 0.0, 4.0, (True, False))
	pg.float('Jitter', 'Jitter', 1.2, 0.0, 10.0, (True, False))
	pg.float('Jitterfreq', 'Jitter Freq', 1.0, 0.0, 4.0, (True, False))
	pg.float('Angularity', 'Jitter Angularity', 0.85)

	pg = _Page(comp, 'Look')
	pg.rgba('Inkcolor', 'Ink Color', (0.0, 0.0, 0.0, 1.0))
	pg.rgba('Papercolor', 'Paper Color', (1.0, 1.0, 1.0, 1.0))
	pg.float('Grain', 'Paper Grain', 0.0)
	pg.header('linedraw TD  /  (c) Ro Mayz 2026  /  after LingDong-/linedraw (MIT)')


def _vecs(glsl, items):
	"""items: list of (uniformName, [x, y, z, w]) where each value is a number or an expression string."""
	try:
		glsl.seq.vec.numBlocks = len(items)
	except Exception:
		pass
	for i, (name, vals) in enumerate(items):
		getattr(glsl.par, 'vec%dname' % i).val = name
		for c, v in zip('xyzw', vals):
			par = getattr(glsl.par, 'vec%dvalue%s' % (i, c))
			if isinstance(v, str):
				par.expr = v
			else:
				par.val = v


def _shader(op_, parname, code, name):
	par = getattr(op_.par, parname)
	d = par.eval()
	if d is None:
		d = op_.parent().create(textDAT, name)
		par.val = d.name
		try:
			d.dock = op_
		except Exception:
			pass
	d.text = code
	return d


def _connect(dst, srcs):
	for i, s in enumerate(srcs):
		dst.inputConnectors[i].connect(s)


def _set(op_, **kw):
	for k, v in kw.items():
		try:
			setattr(getattr(op_.par, k), 'val', v)
		except Exception as e:
			print('linedraw: could not set %s.%s (%s)' % (op_.name, k, e))


def _expr(op_, **kw):
	for k, v in kw.items():
		try:
			getattr(op_.par, k).expr = v
		except Exception as e:
			print('linedraw: could not set %s.%s expr (%s)' % (op_.name, k, e))


def _glsl(comp, name, code, x, y, **common):
	g = comp.create(glslmultiTOP, name)
	g.nodeX, g.nodeY = x, y
	_shader(g, 'pixeldat', code, name + '_pixel')
	_set(g, inputextenduv='hold', **common)
	return g


def build(host=None, name='linedraw1'):
	if host is None:
		try:
			host = me.parent()
		except NameError:
			host = op('/project1') or root
	base, n = name.rstrip('0123456789') or 'linedraw', 1
	while host.op(name):
		n += 1
		name = '%s%d' % (base, n)
	comp = host.create(baseCOMP, name)
	comp.color = (0.12, 0.12, 0.12)
	_add_params(comp)

	util = comp.create(textDAT, 'ld_util')
	util.text = LD_UTIL
	util.nodeX, util.nodeY = -200, 250

	in1 = comp.create(inTOP, 'in1')
	in1.nodeX, in1.nodeY = -200, 0

	# ---- internal G-buffer render (only cooks in Scene mode) ----
	mat = comp.create(glslMAT, 'gbuf_mat')
	mat.nodeX, mat.nodeY = -200, -650
	_shader(mat, 'vdat', SHADERS['gbuffer_vert'], 'gbuf_mat_vertex')
	_shader(mat, 'pdat', SHADERS['gbuffer_frag'], 'gbuf_mat_pixel')
	_vecs(mat, [('uGB', [P + "Gbufspace.menuIndex", 0, 0, 0])])

	rnd = comp.create(renderTOP, 'gbuf_render')
	rnd.nodeX, rnd.nodeY = -200, -450
	_set(rnd, overridemat='gbuf_mat', numcolorbufs=3, antialias='aa1', format='rgba32float',
		 outputresolution='custom', lights='', bgcolorr=0, bgcolorg=0, bgcolorb=0, bgcolora=0)
	_expr(rnd, camera="mod.ld_util.camera(parent())", geometry="mod.ld_util.geometry(parent())",
		  resolutionw="mod.ld_util.res(parent())[0]", resolutionh="mod.ld_util.res(parent())[1]",
		  render=P + "Source.eval() == 'scene'")

	rs1 = comp.create(renderselectTOP, 'gbuf1')
	rs2 = comp.create(renderselectTOP, 'gbuf2')
	for i, r in enumerate((rs1, rs2), 1):
		r.nodeX, r.nodeY = 0, -450 - 150 * i
		_set(r, top='gbuf_render', colorbufindex=i)

	dummy = comp.create(constantTOP, 'no_scene')
	dummy.nodeX, dummy.nodeY = 0, -300
	_set(dummy, outputresolution='custom', resolutionw=4, resolutionh=4, colorr=0, colorg=0, colorb=0, alpha=0, format='rgba32float')

	sws = []
	for i, src in enumerate((rnd, rs1, rs2)):
		s = comp.create(switchTOP, 'g%d' % i)
		s.nodeX, s.nodeY = 200, -300 - 150 * i
		_connect(s, [dummy, src])
		_expr(s, index="1 if parent().par.Source.eval() == 'scene' else 0")
		sws.append(s)

	rtsel = comp.create(selectTOP, 'rt_select')
	rtsel.nodeX, rtsel.nodeY = -200, -150
	_expr(rtsel, top="mod.ld_util.rtpath(parent())")

	tsrc = comp.create(switchTOP, 'tone_src')
	tsrc.nodeX, tsrc.nodeY = 0, 0
	_connect(tsrc, [in1, rtsel, rnd])
	_expr(tsrc, index="mod.ld_util.tonesrc(parent())")

	# ---- 2D chain ----
	lev = _glsl(comp, 'levels', SHADERS['levels'], 200, 150, outputresolution='custom', resolutionw=1, resolutionh=1,
				format='rgba32float', inputfiltertype='mipmap')
	_connect(lev, [tsrc])
	_vecs(lev, [('uCutoff', [P + 'Cutoff', 0, 0, 0])])

	scene = "(1 if parent().par.Source.eval() == 'scene' else 0)"
	prep = _glsl(comp, 'prep', SHADERS['prep'], 400, 0, format='rgba16float')
	_connect(prep, [tsrc, lev, sws[0], sws[1]])
	_vecs(prep, [
		('uLevels', [P + 'Autolevels', P + 'Blackpoint', P + 'Whitepoint', P + 'Gamma']),
		('uTone', [P + 'Contrast', P + 'Brightness', P + 'Invert', P + 'Shademode.menuIndex']),
		('uLight', [P + 'Lightdirx', P + 'Lightdiry', P + 'Lightdirz', P + 'Ambient']),
		('uScene', [scene, "(0 if parent().par.Toneimage.eval() == 'none' else 1)", P + 'Hatchbg', 0]),
	])

	edges = _glsl(comp, 'edges', SHADERS['edges'], 600, 0, outputresolution='custom', format='rgba16float',
				  inputfiltertype='mipmap')
	_connect(edges, [prep, sws[0], sws[1]])
	_expr(edges,
		  resolutionw="max(1, round(parent().par.Designwidth.eval() / max(1, parent().par.Contoursimplify.eval())))",
		  resolutionh="max(1, round(me.par.resolutionw.eval() * op('prep').height / max(1, op('prep').width)))")
	_vecs(edges, [
		('uCanny', [P + 'Lowthresh', P + 'Highthresh', P + 'Imageedges', 0]),
		('uGeo', [P + 'Depthedges', P + 'Depththresh', P + 'Normaledges', P + 'Normalangle']),
		('uGeo2', [P + 'Idedges', scene, 0, 0]),
	])

	hyst = _glsl(comp, 'hyst', SHADERS['hyst'], 800, 0, format='rgba16float')
	_connect(hyst, [edges])
	_expr(hyst, npasses="max(1, int(parent().par.Hysteresis.eval()))")
	_vecs(hyst, [('uHyst', ["max(1, int(parent().par.Hysteresis.eval()))", P + 'Specks', 0, 0])])

	chords = _glsl(comp, 'chords', SHADERS['chords'], 1000, 0, outputresolution='custom', format='rgba32float')
	_connect(chords, [hyst])
	_expr(chords,
		  resolutionw="max(1, -(-op('hyst').width // max(2, int(parent().par.Chordlength.eval()))))",
		  resolutionh="max(1, -(-op('hyst').height // max(2, int(parent().par.Chordlength.eval()))))")
	_vecs(chords, [('uChord', [P + 'Chordlength', 0, 0, 0])])

	ink = _glsl(comp, 'ink', SHADERS['ink'], 1200, 0, format='rgba16float', inputfiltertype='mipmap')
	_connect(ink, [prep, hyst, chords, sws[0], sws[1], sws[2]])
	_expr(ink, outputresolution="'custom' if parent().par.Outputres.eval() == 'custom' else 'useinput'",
		  resolutionw=P + 'Resolution1', resolutionh=P + 'Resolution2')
	L = lambda i: ["(parent().par.L%dthresh.eval() if parent().par.L%don.eval() else -1)" % (i, i),
				   P + 'L%dangle' % i, P + 'L%dphase' % i, P + 'L%dspacing' % i]
	_vecs(ink, [
		('uGlobal', [P + 'Designwidth',
					 "parent().par.Seed.eval() + (int(absTime.seconds * parent().par.Boilrate.eval()) if parent().par.Boilrate.eval() > 0 else 0)",
					 P + 'Softness', P + 'Output.menuIndex']),
		('uInk', [P + 'Inkcolorr', P + 'Inkcolorg', P + 'Inkcolorb', P + 'Inkcolora']),
		('uPaper', [P + 'Papercolorr', P + 'Papercolorg', P + 'Papercolorb', P + 'Papercolora']),
		('uHatch', ["parent().par.Hatch.eval() * parent().par.Hatchopacity.eval()", P + 'Hatchsize', P + 'Hatchweight',
					P + 'Hatchspace.menuIndex']),
		('uHatch2', [P + 'Cellquant', P + 'Wobble', P + 'Wobblefreq', P + 'Weightvar']),
		('uHatch3', [P + 'Gaps',
					 "parent().par.Uvspacing.eval() if parent().par.Hatchspace.eval() == 'uv' else parent().par.Surfacespacing.eval()",
					 P + 'Grain', scene]),
		('uHatch4', [P + 'Surfacelod', P + 'Loddensity',
					 "parent().par.Cliptogeo.eval() * (0 if parent().par.Hatchbg.eval() else 1)", 0]),
		('uL1', L(1)), ('uL2', L(2)), ('uL3', L(3)), ('uL4', L(4)),
		('uCont', ["parent().par.Contours.eval() * parent().par.Contouropacity.eval()", P + 'Contourweight',
				   P + 'Sketchpasses', P + 'Angularity']),
		('uCont2', [P + 'Displace', P + 'Displacefreq', P + 'Jitter', P + 'Jitterfreq']),
		('uCont3', [P + 'Contourstyle.menuIndex', P + 'Chordlength', 0, 0]),
	])

	out = comp.create(outTOP, 'out1')
	out.nodeX, out.nodeY = 1400, 0
	_connect(out, [ink])
	comp.viewer = True
	print('linedraw: built', comp.path)
	return comp


def build_demo(host=None):
	"""A tiny scene: Scene mode (render-aware) next to Image mode on the same render."""
	if host is None:
		try:
			host = me.parent()
		except NameError:
			host = op('/project1') or root
	name, n = 'linedraw_demo', 1
	while host.op(name):
		n += 1
		name = 'linedraw_demo%d' % n
	demo = host.create(baseCOMP, name)

	def geo(nm, soptype, x, y, z, sx=1.0, rot_expr=None, **sop_par):
		g = demo.create(geometryCOMP, nm)
		for c in list(g.children):
			c.destroy()
		s = g.create(soptype, 'shape')
		for k, v in sop_par.items():
			_set(s, **{k: v})
		s.render = True
		s.display = True
		_set(g, tx=x, ty=y, tz=z, sx=sx, sy=sx, sz=sx, material=mat.path)
		if rot_expr:
			_expr(g, ry=rot_expr)
		return g

	mat = demo.create(phongMAT, 'phong1')
	_set(mat, diffr=0.8, diffg=0.8, diffb=0.8)
	geo('geo_torus', torusSOP, -1.1, 0.1, 0, rot_expr='absTime.seconds * 25', radx=0.7, rady=0.28, rows=40, cols=60)
	geo('geo_box', boxSOP, 1.0, -0.15, -0.6, rot_expr='35', sizex=1.1, sizey=1.1, sizez=1.1)
	geo('geo_sphere', sphereSOP, 0.2, -0.45, 0.9, sx=0.35, type='polymesh', rows=40, cols=40)
	geo('geo_floor', gridSOP, 0, -0.95, 0, sizex=30, sizey=30, orient='zx')

	cam = demo.create(cameraCOMP, 'cam1')
	_set(cam, tx=0, ty=1.4, tz=5.5, rx=-12)
	lit = demo.create(lightCOMP, 'light1')
	_set(lit, tx=-4, ty=5, tz=4)

	rnd = demo.create(renderTOP, 'render1')
	_set(rnd, camera='cam1', geometry='geo_*', lights='light1', outputresolution='custom', resolutionw=1280, resolutionh=720)

	for i, o in enumerate([mat, demo.op('geo_torus'), demo.op('geo_box'), demo.op('geo_sphere'), demo.op('geo_floor'), cam, lit]):
		o.nodeX, o.nodeY = -600, 300 - 150 * i
	rnd.nodeX, rnd.nodeY = -300, 0

	ld_scene = build(demo, 'linedraw_scene')
	ld_scene.nodeX, ld_scene.nodeY = 0, 100
	ld_scene.par.Source = 'scene'
	ld_scene.par.Rendertop = 'render1'
	ld_scene.par.Hatchspace = 'surface'

	ld_img = build(demo, 'linedraw_image')
	ld_img.nodeX, ld_img.nodeY = 0, -150
	ld_img.inputConnectors[0].connect(rnd)
	print('linedraw: built demo', demo.path)
	return demo


if BUILD_COMPONENT:
	build()
if BUILD_DEMO:
	build_demo()
