# SPDX-License-Identifier: MIT
cmake_minimum_required(VERSION 3.24)

project(
    trecap_golden
    VERSION 0.1.0
    DESCRIPTION "T-RECAP Phase 2 bit-accurate golden model and artifact tools"
    LANGUAGES CXX
)

include(GNUInstallDirs)
include(CTest)

option(TRECAP_BUILD_TOOLS "Build golden-model command-line tools" ON)
option(TRECAP_BUILD_TESTS "Build C++ self-tests" ON)
option(TRECAP_ENABLE_WARNINGS_AS_ERRORS "Treat compiler warnings as errors" OFF)
option(TRECAP_ENABLE_SANITIZERS "Enable address/undefined sanitizers on supported compilers" OFF)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

if(NOT CMAKE_BUILD_TYPE AND NOT CMAKE_CONFIGURATION_TYPES)
    set(CMAKE_BUILD_TYPE RelWithDebInfo CACHE STRING "Build type" FORCE)
endif()

add_library(trecap_project_options INTERFACE)
target_compile_features(trecap_project_options INTERFACE cxx_std_20)

target_compile_definitions(
    trecap_project_options
    INTERFACE
        TRECAP_GOLDEN_VERSION_MAJOR=${PROJECT_VERSION_MAJOR}
        TRECAP_GOLDEN_VERSION_MINOR=${PROJECT_VERSION_MINOR}
        TRECAP_GOLDEN_VERSION_PATCH=${PROJECT_VERSION_PATCH}
)

add_library(trecap_project_warnings INTERFACE)
if(MSVC)
    target_compile_options(trecap_project_warnings INTERFACE /W4 /permissive-)
    if(TRECAP_ENABLE_WARNINGS_AS_ERRORS)
        target_compile_options(trecap_project_warnings INTERFACE /WX)
    endif()
else()
    target_compile_options(
        trecap_project_warnings
        INTERFACE
            -Wall
            -Wextra
            -Wpedantic
            -Wconversion
            -Wsign-conversion
            -Wshadow
            -Wdouble-promotion
            -Wformat=2
            -Wundef
    )
    if(TRECAP_ENABLE_WARNINGS_AS_ERRORS)
        target_compile_options(trecap_project_warnings INTERFACE -Werror)
    endif()
endif()

if(TRECAP_ENABLE_SANITIZERS AND NOT MSVC)
    target_compile_options(trecap_project_options INTERFACE -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(trecap_project_options INTERFACE -fsanitize=address,undefined)
endif()

file(GLOB TRECAP_GOLDEN_HEADERS CONFIGURE_DEPENDS include/trecap_golden/*.hpp)
file(GLOB TRECAP_GOLDEN_SOURCES CONFIGURE_DEPENDS src/*.cpp)

if(TRECAP_GOLDEN_SOURCES)
    add_library(trecap_golden STATIC ${TRECAP_GOLDEN_SOURCES} ${TRECAP_GOLDEN_HEADERS})
    target_include_directories(
        trecap_golden
        PUBLIC
            $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
            $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
    )
    target_link_libraries(trecap_golden PUBLIC trecap_project_options trecap_project_warnings)
else()
    add_library(trecap_golden INTERFACE)
    target_include_directories(
        trecap_golden
        INTERFACE
            $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
            $<INSTALL_INTERFACE:${CMAKE_INSTALL_INCLUDEDIR}>
    )
    target_link_libraries(trecap_golden INTERFACE trecap_project_options trecap_project_warnings)
endif()

if(TRECAP_BUILD_TOOLS AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/tools/phase2_golden_model.cpp")
    add_executable(phase2_golden_model tools/phase2_golden_model.cpp)
    target_link_libraries(phase2_golden_model PRIVATE trecap_golden trecap_project_options trecap_project_warnings)
endif()

if(TRECAP_BUILD_TOOLS AND EXISTS "${CMAKE_CURRENT_SOURCE_DIR}/tools/artifact_check.cpp")
    add_executable(trecap_artifact_check tools/artifact_check.cpp)
    target_link_libraries(trecap_artifact_check PRIVATE trecap_golden trecap_project_options trecap_project_warnings)
endif()

if(TRECAP_BUILD_TESTS AND BUILD_TESTING)
    file(GLOB TRECAP_CPP_TESTS CONFIGURE_DEPENDS tests/cpp/test_*.cpp)
    foreach(test_src IN LISTS TRECAP_CPP_TESTS)
        get_filename_component(test_name "${test_src}" NAME_WE)
        add_executable(${test_name} ${test_src})
        target_link_libraries(${test_name} PRIVATE trecap_golden trecap_project_options trecap_project_warnings)
        add_test(NAME ${test_name} COMMAND ${test_name})
    endforeach()
endif()

install(
    TARGETS trecap_golden trecap_project_options trecap_project_warnings
    EXPORT trecap_goldenTargets
    ARCHIVE DESTINATION ${CMAKE_INSTALL_LIBDIR}
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
    INCLUDES DESTINATION ${CMAKE_INSTALL_INCLUDEDIR}
)

install(DIRECTORY include/ DESTINATION ${CMAKE_INSTALL_INCLUDEDIR})

install(
    EXPORT trecap_goldenTargets
    NAMESPACE trecap::
    DESTINATION ${CMAKE_INSTALL_LIBDIR}/cmake/trecap_golden
)

message(STATUS "T-RECAP golden model ${PROJECT_VERSION}")
message(STATUS "C++ standard: ${CMAKE_CXX_STANDARD}")
message(STATUS "Build type: ${CMAKE_BUILD_TYPE}")
message(STATUS "Build tools: ${TRECAP_BUILD_TOOLS}")
message(STATUS "Build tests: ${TRECAP_BUILD_TESTS}")
