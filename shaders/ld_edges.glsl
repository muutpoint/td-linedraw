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
