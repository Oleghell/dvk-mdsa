"""Reproduce low-FPS short-chat cost, on owned native fixtures only.

Run with the compiled fixtures/one_chat_fixture.c library. Compares the former
one-item policy and adaptive batches using the SAME current identity/stability
checks. Native invocation counts/frame counts are checked; wall time is printed,
not asserted as a flaky deadline or a live-MuMu performance claim.
"""
import json
from pathlib import Path
import subprocess
import sys
import time
from unittest.mock import patch
import one_chat_probe as probe
import smoke_one_chat as smoke


def main(library):
    build = probe.build
    original_popen = subprocess.Popen
    who = dict(account='100', peer='200', chat='300')

    def one_item(*args, **kwargs):
        source = build(*args, **kwargs)
        assert source.count('const chunkSize=4;') == 1
        return source.replace('const chunkSize=4;', 'const chunkSize=first<=16?1:4;', 1)

    def low_fps_child(command, *args, **kwargs):
        command = list(command)
        assert 'time.sleep(.003)' in command[3]
        command[3] = command[3].replace('time.sleep(.003)', 'time.sleep(.066)')
        return original_popen(command, *args, **kwargs)

    rows = []
    with patch.object(smoke.subprocess, 'Popen', side_effect=low_fps_child):
        for variant, builder in (('one-item', one_item), ('adaptive', build)):
            with patch.object(probe, 'build', side_effect=builder):
                for trial in range(3):
                    started = time.perf_counter()
                    counters = smoke.one(library, 585, who)
                    assert counters['samples'] == 2
                    rows.append(dict(variant=variant, trial=trial+1,
                        elapsed_ms=round((time.perf_counter()-started)*1000), **counters))
    baseline, current = rows[:3], rows[3:]
    assert all(new['frames'] < old['frames'] and new['managed_calls'] < old['managed_calls']
               for old, new in zip(baseline, current))
    print(json.dumps(dict(synthetic=True, live_mumu_verified=False, messages=16,
        frame_interval_ms=66, results=rows), indent=2))


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve(strict=True))
