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
