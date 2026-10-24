"""Compile the actual Windows clock helper with deterministic QPC stubs."""
from pathlib import Path
import shutil,subprocess,tempfile,unittest

ROOT=Path(__file__).resolve().parents[1]
class FixtureClock(unittest.TestCase):
    @unittest.skipUnless(shutil.which('cc'),'C compiler needed for QPC stub test')
    def test_qpc_conversion_preserves_spacing_and_large_uptime(self):
        source=r'''
#include <stdint.h>
#define _WIN32
/* Windows types already provided by root_fixture.c in real fixtures. */
typedef struct { long long QuadPart; } LARGE_INTEGER;
static long long ticks;
static int QueryPerformanceFrequency(LARGE_INTEGER *p){p->QuadPart=10000000;return 1;}
static int QueryPerformanceCounter(LARGE_INTEGER *p){p->QuadPart=ticks;return 1;}
#include "fixture_clock.h"
int main(void){
 ticks=123456789;uint64_t before=clock_ms();
 ticks+=10000000;if(clock_ms()-before!=1000)return 1;
 ticks=9876543210987654LL;
 if(clock_ms()!=987654321098ULL)return 2;
 ticks=9999;if(clock_ms()!=0)return 3;
 ticks=10000;if(clock_ms()!=1)return 4;
 return 0;
}
'''
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder);(p/'clock.c').write_text(source)
            subprocess.run(['cc','-std=c11','-I',str(ROOT/'fixtures'),str(p/'clock.c'),'-o',str(p/'clock')],check=True,capture_output=True)
            subprocess.run([str(p/'clock')],check=True,capture_output=True)
    def test_both_native_fixtures_use_same_precise_clock_without_weakening_gate(self):
        for name in ('automatic_fixture.c','profile_navigation_fixture.c'):
            text=(ROOT/'fixtures'/name).read_text()
            self.assertIn('#include "fixture_clock.h"',text)
            self.assertNotIn('return GetTickCount64()',text)
        self.assertIn('now-auto_last_action<990',(ROOT/'fixtures/automatic_fixture.c').read_text())
