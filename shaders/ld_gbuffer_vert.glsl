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
