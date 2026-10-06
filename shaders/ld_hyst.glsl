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
