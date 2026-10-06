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
