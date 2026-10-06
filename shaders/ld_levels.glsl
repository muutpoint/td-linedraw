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
