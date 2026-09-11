# LLVM toolchain for Windows ARM64 (native on a Windows-on-Arm runner).
#
# MSVC must be set up in the environment before invoking CMake, for example
# with vcvarsall.bat arm64 or ilammy/msvc-dev-cmd with arch: arm64.

# ARM64 has the MSVC ABI; only compiler-rt is applicable on Windows.
set(LLVM_ENABLE_RUNTIMES "compiler-rt" CACHE STRING "")
set(LLVM_DEFAULT_TARGET_TRIPLE "aarch64-pc-windows-msvc" CACHE STRING "")

# ARM64 support
set(CMAKE_SYSTEM_NAME Windows)
set(CMAKE_SYSTEM_PROCESSOR ARM64)
set(CMAKE_GENERATOR_PLATFORM ARM64 CACHE STRING "")

include("${CMAKE_CURRENT_LIST_DIR}/initial-cache.cmake")
