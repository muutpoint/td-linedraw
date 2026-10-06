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
