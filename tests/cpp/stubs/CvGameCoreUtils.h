// Stand-in for CvGameCoreUtils.h: the helpers CvFractal.cpp uses, copied verbatim from
// CvGameCoreDLL_Expansion2/CvGameCoreUtils.h/.cpp (range, wrapCoordDifference, dxWrap, dyWrap,
// xToHexspaceX, hexDistance, hexspaceDirections, estimateDirection).
#pragma once

inline int range(int iNum, int iLow, int iHigh)
{
	if(iNum < iLow)
	{
		return iLow;
	}
	else if(iNum > iHigh)
	{
		return iHigh;
	}
	else
	{
		return iNum;
	}
}

inline int wrapCoordDifference(int iDiff, uint uiRange, bool bWrap)
{
	if(bWrap)
	{
		if(iDiff > (int)(uiRange >> 1))
		{
			return (iDiff - (int)uiRange);
		}
		else if(iDiff < -(int)(uiRange >> 1))
		{
			return (iDiff + (int)uiRange);
		}
	}

	return iDiff;
}

inline int dxWrap(int iDX)
{
	const CvMapStub& kMap = GC.getMap();
	return wrapCoordDifference(iDX, kMap.getGridWidth(), kMap.isWrapX());
}

inline int dyWrap(int iDY)
{
	const CvMapStub& kMap = GC.getMap();
	return wrapCoordDifference(iDY, kMap.getGridHeight(), kMap.isWrapY());
}

inline int xToHexspaceX(int iX, int iY)
{
	return iX - ((iY >= 0) ? (iY>>1) : ((iY - 1)/2));
}

inline int hexDistance(int iDX, int iDY)
{
	if((iDX >= 0) == (iDY >= 0))
	{
		int iAbsDX = iDX >= 0 ? iDX : -iDX;
		int iAbsDY = iDY >= 0 ? iDY : -iDY;
		return iAbsDX + iAbsDY;
	}
	else
	{
		int iAbsDX = iDX >= 0 ? iDX : -iDX;
		int iAbsDY = iDY >= 0 ? iDY : -iDY;
		return iAbsDX >= iAbsDY ? iAbsDX : iAbsDY;
	}
}

static float hexspaceDirections[6][3] = {
	{0, 1, -1}, //ne
	{1, 0, -1}, //e
	{1, -1, 0}, //se
	{0, -1, 1}, //sw
	{-1, 0, 1}, //w
	{-1, 1, 0}, //nw
};

inline DirectionTypes estimateDirection(int iStartX, int iStartY, int iDestX, int iDestY)
{
	int iStartXHex = xToHexspaceX(iStartX,iStartY);
	int iDestXHex = xToHexspaceX(iDestX,iDestY);

	int iDX = dxWrap(iDestXHex - iStartXHex);
	int iDY = dyWrap(iDestY - iStartY);

	if (iDX==0 && iDY==0)
		return NO_DIRECTION;

	int iStartZ = -iStartXHex-iStartY;
	int iDestZ = -iDestXHex-iDestY;
	int iDZ = iDestZ - iStartZ;

	float maximum = 0;
	int maximumIndex = -1;
	for(int i=0; i<6; i++)
	{
		float dotProduct = iDX * hexspaceDirections[i][0] + iDY * hexspaceDirections[i][1] + iDZ * hexspaceDirections[i][2];
		if(dotProduct > maximum)
		{
			maximum = dotProduct;
			maximumIndex = i;
		}
	}

	return (DirectionTypes)maximumIndex;
}
