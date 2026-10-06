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
