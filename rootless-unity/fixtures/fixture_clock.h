/* Monotonic milliseconds for owned native test fixtures, not application code. */
#ifndef DVK_FIXTURE_CLOCK_H
#define DVK_FIXTURE_CLOCK_H
#include <stdint.h>
#ifdef _WIN32
#include <stdlib.h>
static uint64_t clock_ms(void){
 LARGE_INTEGER counter,frequency;
 /* GetTickCount64 has ~10-16 ms resolution; it can falsely fail the
    unchanged 990 ms action-spacing assertion around a 1000 ms deadline. */
 if(!QueryPerformanceFrequency(&frequency)||frequency.QuadPart<=0||
    !QueryPerformanceCounter(&counter)||counter.QuadPart<0)abort();
 uint64_t ticks=(uint64_t)counter.QuadPart,hz=(uint64_t)frequency.QuadPart;
 return (ticks/hz)*1000+(ticks%hz)*1000/hz;
}
#else
#include <time.h>
static uint64_t clock_ms(void){
 struct timespec ts;clock_gettime(CLOCK_MONOTONIC,&ts);
 return (uint64_t)ts.tv_sec*1000+ts.tv_nsec/1000000;
}
#endif
#endif
