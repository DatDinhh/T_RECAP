# SPDX-License-Identifier: MIT
# T-RECAP Phase 2 root CMake configuration.
# File class: [1] hand-written repository infrastructure.
#
# CMake is used for host-side C/C++ builds only: the imported reference model
# and the HPS userspace streamer. RTL compile order, Quartus builds, generated
# headers, and artifact production are orchestrated by the root Makefile and
# project scripts.

cmake_minimum_required(VERSION 3.24)

project(
    trecap_phase2
    VERSION 0.1.0
    DESCRIPTION "T-RECAP Phase 2 FPGA/HPS/PC implementation repository"
    LANGUAGES C CXX
)

include(CTest)
include(GNUInstallDirs)

option(TRECAP_BUILD_REFERENCE_MODEL "Build imported Phase 2 reference-model package" ON)
option(TRECAP_BUILD_HPS "Build HPS userspace UDP streamer when sources exist" ON)
option(TRECAP_BUILD_TESTS "Build host-side C/C++ tests when present" ON)
option(TRECAP_ENABLE_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" OFF)
option(TRECAP_ENABLE_SANITIZERS "Enable address/undefined sanitizers on supported host compilers" OFF)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS OFF)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "Build type" FORCE)
endif()

find_package(Python3 COMPONENTS Interpreter)

add_library(trecap_root_project_options INTERFACE)
target_compile_features(trecap_root_project_options INTERFACE cxx_std_20)
target_compile_definitions(
    trecap_root_project_options
    INTERFACE
        TRECAP_PHASE2_VERSION_MAJOR=${PROJECT_VERSION_MAJOR}
        TRECAP_PHASE2_VERSION_MINOR=${PROJECT_VERSION_MINOR}
        TRECAP_PHASE2_VERSION_PATCH=${PROJECT_VERSION_PATCH}
)

add_library(trecap_root_project_warnings INTERFACE)
if(MSVC)
    target_compile_options(trecap_root_project_warnings INTERFACE /W4 /permissive-)
    if(TRECAP_ENABLE_WARNINGS_AS_ERRORS)
        target_compile_options(trecap_root_project_warnings INTERFACE /WX)
    endif()
else()
    target_compile_options(
        trecap_root_project_warnings
        INTERFACE
            -Wall
            -Wextra
            -Wpedantic
            -Wconversion
            -Wsign-conversion
            -Wshadow
            -Wformat=2
            -Wundef
    )
    if(TRECAP_ENABLE_WARNINGS_AS_ERRORS)
        target_compile_options(trecap_root_project_warnings INTERFACE -Werror)
    endif()
endif()

if(TRECAP_ENABLE_SANITIZERS AND NOT MSVC)
    target_compile_options(trecap_root_project_options INTERFACE -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(trecap_root_project_options INTERFACE -fsanitize=address,undefined)
endif()

# -----------------------------------------------------------------------------
# Imported reference-model package.
# Current implementation naming uses sw/reference_model. sw/golden is accepted
# only as a compatibility fallback for spec text or older imports.
# -----------------------------------------------------------------------------
set(TRECAP_REFERENCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/sw/reference_model")
if(NOT EXISTS "${TRECAP_REFERENCE_DIR}/CMakeLists.txt" AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/sw/golden/CMakeLists.txt")
    set(TRECAP_REFERENCE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/sw/golden")
endif()

if(TRECAP_BUILD_REFERENCE_MODEL AND EXISTS "${TRECAP_REFERENCE_DIR}/CMakeLists.txt")
    add_subdirectory("${TRECAP_REFERENCE_DIR}" "${CMAKE_BINARY_DIR}/reference_model")
    message(STATUS "Reference model enabled: ${TRECAP_REFERENCE_DIR}")
else()
    message(STATUS "Reference model not added; import it under sw/reference_model/ to enable host build")
endif()

# -----------------------------------------------------------------------------
# HPS userspace streamer.
# This target is deliberately transport/control only. It must include generated
# CSR/packet headers and must not contain STFT, FFT, IFFT, masking, WOLA, or
# reconstruction algorithms.
# -----------------------------------------------------------------------------
set(TRECAP_HPS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/sw/hps")
set(TRECAP_HPS_SOURCES
    "${TRECAP_HPS_DIR}/src/main.c"
    "${TRECAP_HPS_DIR}/src/trecap_udp_streamer.c"
    "${TRECAP_HPS_DIR}/src/config.c"
    "${TRECAP_HPS_DIR}/src/csr_map.c"
    "${TRECAP_HPS_DIR}/src/ring_reader.c"
    "${TRECAP_HPS_DIR}/src/udp_sender.c"
    "${TRECAP_HPS_DIR}/src/command_server.c"
    "${TRECAP_HPS_DIR}/src/command_bridge.c"
    "${TRECAP_HPS_DIR}/src/status_patch.c"
)

set(TRECAP_HPS_PRESENT TRUE)
foreach(src IN LISTS TRECAP_HPS_SOURCES)
    if(NOT EXISTS "${src}")
        set(TRECAP_HPS_PRESENT FALSE)
    endif()
endforeach()

if(TRECAP_BUILD_HPS AND TRECAP_HPS_PRESENT)
    add_executable(trecap_udp_streamer ${TRECAP_HPS_SOURCES})
    target_include_directories(
        trecap_udp_streamer
        PRIVATE
            "${TRECAP_HPS_DIR}/include"
            "${TRECAP_HPS_DIR}/include/generated"
    )
    target_link_libraries(trecap_udp_streamer PRIVATE trecap_root_project_warnings)
    target_compile_definitions(trecap_udp_streamer PRIVATE _POSIX_C_SOURCE=200809L)
    if(UNIX AND NOT APPLE)
        target_link_libraries(trecap_udp_streamer PRIVATE m)
    endif()
    install(TARGETS trecap_udp_streamer RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR})
    message(STATUS "HPS streamer target enabled")
else()
    message(STATUS "HPS streamer target not added; sw/hps/src is incomplete or TRECAP_BUILD_HPS=OFF")
endif()

# -----------------------------------------------------------------------------
# Root utility targets. They are optional wrappers around the Makefile scripts so
# CMake users can still discover the same project workflow.
# -----------------------------------------------------------------------------
if(Python3_Interpreter_FOUND)
    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/scripts/lint_repo_layout.py")
        add_custom_target(
            trecap_check_layout
            COMMAND Python3::Interpreter "${CMAKE_CURRENT_SOURCE_DIR}/scripts/lint_repo_layout.py"
            WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
            COMMENT "Checking repository layout"
        )
    endif()

    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/scripts/gen_headers.py")
        add_custom_target(
            trecap_gen_headers
            COMMAND Python3::Interpreter "${CMAKE_CURRENT_SOURCE_DIR}/scripts/gen_headers.py"
            WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
            COMMENT "Generating SV/C/Python contract headers"
        )
    endif()

    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/scripts/check_generated.py")
        add_custom_target(
            trecap_check_generated
            COMMAND Python3::Interpreter "${CMAKE_CURRENT_SOURCE_DIR}/scripts/check_generated.py"
            WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
            COMMENT "Checking deterministic generated-header regeneration"
        )
    endif()

    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/scripts/gen_filelists.py")
        add_custom_target(
            trecap_gen_filelists
            COMMAND Python3::Interpreter "${CMAKE_CURRENT_SOURCE_DIR}/scripts/gen_filelists.py"
            WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
            COMMENT "Generating RTL filelists"
        )
    endif()

    if(EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/sw/pc_dashboard/trecap_dashboard")
        add_custom_target(
            trecap_dashboard_import
            COMMAND
                ${CMAKE_COMMAND} -E env
                    PYTHONPATH=${CMAKE_CURRENT_SOURCE_DIR}/sw/pc_dashboard:${CMAKE_CURRENT_SOURCE_DIR}/sw/pc_dashboard/generated
                    Python3::Interpreter -c "import trecap_dashboard.packet_parser; print('dashboard-import: OK')"
            WORKING_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}"
            COMMENT "Checking Python dashboard imports"
        )
    endif()
endif()

# Host-side tests outside the imported reference model may be added later under
# tests/cpp. Verification architecture is intentionally not defined here.
if(TRECAP_BUILD_TESTS AND BUILD_TESTING)
    file(GLOB TRECAP_HOST_CPP_TESTS CONFIGURE_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/tests/cpp/test_*.cpp")
    foreach(test_src IN LISTS TRECAP_HOST_CPP_TESTS)
        get_filename_component(test_name "${test_src}" NAME_WE)
        add_executable(${test_name} "${test_src}")
        target_link_libraries(${test_name} PRIVATE trecap_root_project_options trecap_root_project_warnings)
        add_test(NAME ${test_name} COMMAND ${test_name})
    endforeach()
endif()

message(STATUS "T-RECAP Phase 2 root ${PROJECT_VERSION}")
message(STATUS "Build type: ${CMAKE_BUILD_TYPE}")
message(STATUS "Reference dir: ${TRECAP_REFERENCE_DIR}")
message(STATUS "Build reference model: ${TRECAP_BUILD_REFERENCE_MODEL}")
message(STATUS "Build HPS streamer: ${TRECAP_BUILD_HPS}")
message(STATUS "Build tests: ${TRECAP_BUILD_TESTS}")
