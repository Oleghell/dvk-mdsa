# CI checks and Windows package

The `mumu` push workflow builds the Windows package independently of verification. A release cannot be published until **all** unit, native and packaging jobs succeed.

## Unit tests

- Linux runs the complete suite once.
- Windows runs three independent jobs. `run_unit_tests.py` discovers the complete suite in each job, then deterministically assigns whole Python test modules to shards, balancing by discovered test count. Class/module fixtures and duplicate discoveries remain intact; an import error is still a failing test.
- No previously green result is reused and no safety tests are skipped to improve timing. The default local command remains `python rootless-unity/run_unit_tests.py`.
- To reproduce the Windows division locally, run indices `0`, `1` and `2` with `--shard-count 3 --shard-index INDEX`. All three must pass. A single shard is not a complete verification.
- Each job prints its slowest modules. GitHub uploads `unit-timings-*` summaries with counts and timings, including failed runs, so future tuning can use measured Windows times rather than guesses.

## Native tests

Linux and Windows each run all 13 ABI suites on independent runners, in parallel with unit tests. The native runner still uses three isolated processes and compiles every fixture; longer suites are scheduled first to reduce the tail. Message-delivery checks, identity checks, two-snapshot stability, frame budgets and preflight assertions are unchanged.

The owned dialog-browser fixture child has a finite five-minute fallback lifetime instead of an unrelated roughly 36-second lifetime. Normal tests terminate it immediately in `finally`. This does not change production waits or bypass a native failure; it prevents the child from disappearing during a valid slower host-side integration run.

## Packaging

The existing dependency caches, shared PyInstaller onedir analysis, GUI/worker self-checks, manifest, single ZIP compression and checksum are retained. The package job does not wait for unit/native jobs, but the release job requires all of them. Superseded branch runs are cancelled by the existing concurrency policy.

GitHub queue time and runner availability are outside the workflow's control. The new critical path must be measured on a real Windows run; local Linux timings are not Windows speed guarantees.
