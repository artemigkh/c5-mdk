// Cross-check harness: links the UNMODIFIED CvRandom.cpp / CvFractal.cpp from the VP DLL source
// (copied next to the stub headers by build_and_compare.py) and prints results for test cases
// read from stdin. The Lua port prints the same format; the Python script diffs them.
//
// Input lines:
//   RNG   <seed> <count> <num>        -> count draws of get(num)
//   FLOAT <seed> <count>              -> count getFloat() values (printed as %.9g)
//   FRAC  <seed> <W> <H> <grain> <flags> <xexp> <yexp> <riftGrain> <ridgeSeeds> <ridgeFlags>
//         <blendRidge> <blendFract> <mapW> <mapH> <mapWrapX> <mapWrapY>
//         -> rand.init(seed); [rifts = fracInit(W,H,riftGrain,rand,0,NULL,xexp,yexp)]
//            frac.fracInit(W,H,grain,rand,flags,rifts?,xexp,yexp); [frac.ridgeBuilder(...)]
//            prints getHeight for every (x,y) (y-major), getHeightFromPercent(0..100 step 5),
//            and the final RNG seed as two 32-bit halves (hi lo)
#include "CvGameCoreDLLPCH.h"
#include "CvRandom.h"
#include "CvFractal.h"
#include <iostream>
#include <sstream>

CvGlobalsStub GC;
CvDLLStub g_dllStub;
CvDLLStub* gDLL = &g_dllStub;

int main()
{
	std::string line;
	while (std::getline(std::cin, line))
	{
		std::istringstream in(line);
		std::string kind;
		if (!(in >> kind)) continue;
		if (kind == "RNG")
		{
			unsigned long long seed; int count; unsigned long num;
			in >> seed >> count >> num;
			CvRandom r("test");
			r.init(seed);
			printf("RNG");
			for (int i = 0; i < count; i++) printf(" %lu", r.get(num, "t"));
			printf("\nSEED %lu %lu\n", (unsigned long)(r.getSeed() >> 32), (unsigned long)(r.getSeed() & 0xffffffffULL));
		}
		else if (kind == "FLOAT")
		{
			unsigned long long seed; int count;
			in >> seed >> count;
			CvRandom r("test");
			r.init(seed);
			printf("FLOAT");
			for (int i = 0; i < count; i++) printf(" %.9g", (double)r.getFloat());
			printf("\nSEED %lu %lu\n", (unsigned long)(r.getSeed() >> 32), (unsigned long)(r.getSeed() & 0xffffffffULL));
		}
		else if (kind == "FRAC")
		{
			unsigned long long seed;
			int W, H, grain, flags, xexp, yexp, riftGrain, ridgeSeeds, ridgeFlags, br, bf, mw, mh, mwx, mwy;
			in >> seed >> W >> H >> grain >> flags >> xexp >> yexp >> riftGrain >> ridgeSeeds >> ridgeFlags >> br >> bf >> mw >> mh >> mwx >> mwy;
			GC.map.w = mw; GC.map.h = mh; GC.map.wx = mwx != 0; GC.map.wy = mwy != 0;
			CvRandom r("map");
			r.init(seed);
			CvFractal* rifts = NULL;
			if (riftGrain > 0)
			{
				rifts = new CvFractal();
				rifts->fracInit(W, H, riftGrain, r, 0, NULL, xexp, yexp);
			}
			CvFractal* f = new CvFractal();
			f->fracInit(W, H, grain, r, flags, rifts, xexp, yexp);
			if (ridgeSeeds > 0)
				f->ridgeBuilder(r, ridgeSeeds, ridgeFlags, br, bf);
			printf("H");
			for (int y = 0; y < H; y++)
				for (int x = 0; x < W; x++)
					printf(" %d", f->getHeight(x, y));
			printf("\nP");
			for (int p = 0; p <= 100; p += 5) printf(" %d", f->getHeightFromPercent(p));
			printf("\nSEED %lu %lu\n", (unsigned long)(r.getSeed() >> 32), (unsigned long)(r.getSeed() & 0xffffffffULL));
			delete f;
			delete rifts;
		}
		fflush(stdout);
	}
	return 0;
}
