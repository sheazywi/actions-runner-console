# Persistent builds without stale results

A self-hosted runner normally keeps its disk between jobs. The dashboard leaves your workspace and caches alone. GitHub's checkout step and your build scripts decide what survives.

## Preserve trusted workspaces

For trusted branch jobs on a persistent machine, explicitly preserve ignored build directories:

```yaml
- uses: actions/checkout@v6.0.2
  with:
    clean: ${{ runner.environment != 'self-hosted' }}
    submodules: recursive
    lfs: true
    persist-credentials: false
```

Keep pull requests from outside contributors on disposable hosted runners. Do not share writable caches or persistent workspaces between trusted and untrusted jobs.

This setting alone is not sufficient: deleted sources, changed generators and changed toolchains must still produce correct results. Always regenerate build descriptions, let the compiler's dependency tracker validate headers, and invalidate generated build trees when compiler/SDK/build flags change.

## Separate configurations

Use different object/build directories for Debug, Release, sanitizer builds and different architectures:

```bash
cmake -S . -B build/release -DCMAKE_BUILD_TYPE=Release
cmake --build build/release --parallel 4
ctest --test-dir build/release --output-on-failure
```

Use `build/debug` for Debug. Do not repeatedly change one CMake build directory between incompatible generators or compilers. On Windows, use the matching `--config Release` for a multi-configuration generator.

Do not persist stale release packages or old logs alongside new results. Recreate packaging directories from the current build and check the files you intend to publish.

## Keep package caches outside the checkout

Useful defaults already persist on dedicated machines:

| Tool | Typical local cache |
|---|---|
| NuGet | `~/.nuget/packages` |
| pip | platform user cache (check `python -m pip cache dir`) |
| Git LFS | repository `.git/lfs/objects` |
| ccache | a user-owned directory outside the checkout |
| sccache | a user-owned directory outside the checkout |

Provision compilers/SDKs once as an administrator. Jobs should not reinstall them or need sudo/UAC.

For disposable hosted machines, use [actions/cache](https://github.com/actions/cache) for compiler/package caches with keys that include OS, compiler/SDK version and relevant build settings. Save shared caches only from trusted jobs. Avoid caching arbitrary executable workspace contents across trust boundaries.

## Content-based compiler caches

[ccache](https://ccache.dev/manual/latest.html) can reuse Linux C/C++ compilation results even after a clean checkout. [sccache](https://github.com/mozilla/sccache) supports several compilers, including MSVC, but integration depends on your generator.

Keep cache sizes bounded. Do not enable unsafe cache options merely to force hits. A cache miss must invoke the actual compiler. A cache failure must not turn a failed build into success.

Persistent object directories and content-based compiler caches are different tools: the former rely on the build system's dependency graph and timestamps; the latter use compile inputs as keys.

## Avoid invalidating the whole PCH

A generated commit/version header in a shared precompiled header makes every commit invalidate that PCH and its dependents. Include per-build metadata only in the few translation units that display the version. Keep the stable PCH independent of it.

Similarly, do not rewrite generated files when their content has not changed.

## Measure a warm build

1. Run a cold build and retain its duration and compiler/cache statistics.
2. Repeat at the same commit. Confirm that unchanged objects are reused.
3. Change one implementation file. Confirm the affected object and final artifact rebuild.
4. Change a widely included header or compiler setting. Confirm dependent files invalidate.
5. Delete an input/source file and regenerate. Confirm it is no longer linked.
6. Run tests and packaging against the current outputs.

Record both time and correctness. A small fixture showing a cache hit is not a measurement of your full project's build time. Cold builds, large header changes and toolchain changes can still take a long time.

## Cleaning and recovery

Keep a documented cold-build path that removes only known generated directories. Never point a recursive cleanup command at an unchecked path, the whole runner directory, or the source repository root. Stop jobs before manually cleaning a shared workspace.

If you observe checksum corruption or unexplained compiler crashes, quarantine that runner and investigate integrity first. Caching cannot repair unreliable storage or memory.

Further reading: [checkout clean input](https://github.com/actions/checkout/blob/v6.0.2/action.yml), [GitHub cache behavior](https://docs.github.com/en/actions/using-workflows/caching-dependencies-to-speed-up-workflows).
