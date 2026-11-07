// Minimal stand-in for the DLL precompiled header: just enough for the *unmodified*
// CvRandom.cpp / CvFractal.cpp to compile in the standalone cross-check harness.
#pragma once
#include <string>
#include <vector>
#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <climits>
#include <cmath>

typedef unsigned int uint;
typedef unsigned char byte;
typedef unsigned char BYTE;
using std::vector;

#define NODISCARD
#define MAX_UNSIGNED_INT (0xffffffff)
#define ASSERT(...) {}
#define FAssert(x) {}
#define DEBUG_VARIABLE(x) ((void)(x))
#define RAND_LOGGING_ASYNCHRONOUS_FLAG 1
#define RAND_LOGGING_PREGAME_FLAG 2

inline void OutputDebugString(const char*) {}

struct FDataStream {};
struct CvStreamLoadVisitor { CvStreamLoadVisitor(FDataStream&) {} template<class T> void operator()(T&) {} };
struct CvStreamSaveVisitor { CvStreamSaveVisitor(FDataStream&) {} template<class T> void operator()(const T&) {} };

struct FILogFile { enum { kDontTimeStamp = 0 }; void Msg(const char*) {} };
struct FILogFileMgrStub { FILogFile* GetLog(const char*, int) { return 0; } };
static FILogFileMgrStub g_logMgrStub;
#define LOGFILEMGR g_logMgrStub

struct CvGame { int getTurnSlice() { return 0; } int getGameTurn() { return 0; } };
struct CvMapStub {
	int w, h; bool wx, wy;
	int getGridWidth() const { return w; }
	int getGridHeight() const { return h; }
	bool isWrapX() const { return wx; }
	bool isWrapY() const { return wy; }
};
struct CvGlobalsStub {
	CvGame game; CvMapStub map;
	bool getLogging() { return false; }
	int getRandLogging() { return 0; }
	CvGame& getGame() { return game; }
	const CvMapStub& getMap() { return map; }
};
extern CvGlobalsStub GC;
struct CvDLLStub { bool IsGameCoreThread() { return true; } bool IsGameCoreExecuting() { return false; } };
extern CvDLLStub* gDLL;

enum DirectionTypes
{
	NO_DIRECTION = -1,
	DIRECTION_NORTHEAST = 0,
	DIRECTION_EAST,
	DIRECTION_SOUTHEAST,
	DIRECTION_SOUTHWEST,
	DIRECTION_WEST,
	DIRECTION_NORTHWEST,
	NUM_DIRECTION_TYPES
};
