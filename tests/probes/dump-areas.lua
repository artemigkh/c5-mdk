-- c5h --lua-probe: dump every plot's type/terrain/feature/area/landmass/lake flags to Lua.log
-- so the c5maps fake client's area algorithm can be checked against the real DLL.
local w, h = Map.GetGridSize();
print(string.format("C5MAPS_AREAS|begin|w=%d|h=%d|wrapx=%s|areas=%d", w, h, tostring(Map.IsWrapX()), Map.GetIndexAfterLastArea()));
for y = 0, h - 1 do
	local parts = {};
	for x = 0, w - 1 do
		local p = Map.GetPlot(x, y);
		parts[#parts + 1] = string.format("%d:%d:%d:%d:%d:%d:%d",
			p:GetPlotType(), p:GetTerrainType(), p:GetFeatureType(),
			p:GetArea(), p:GetLandmass(), p:IsLake() and 1 or 0, p:IsImpassable() and 1 or 0);
	end
	print("C5MAPS_AREAS|row|" .. y .. "|" .. table.concat(parts, " "));
end
for _, area in Map.Areas() do   -- the iterator yields (index, area) like CvLuaMap::lAreasAux
	print(string.format("C5MAPS_AREAS|area|%d|tiles=%d|water=%s", area:GetID(), area:GetNumTiles(), tostring(area:IsWater())));
end
print("C5MAPS_AREAS|end");
