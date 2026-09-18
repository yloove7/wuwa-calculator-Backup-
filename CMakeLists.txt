cmake_minimum_required(VERSION 3.20)

project(tethys_native LANGUAGES CXX)

set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

option(TETHYS_BUILD_NATIVE "Build the optional C++/pybind11 module" ON)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

if(NOT TETHYS_BUILD_NATIVE)
    message(STATUS "Tethys native module disabled")
    return()
endif()

find_package(Python COMPONENTS Interpreter Development.Module REQUIRED)
find_package(pybind11 CONFIG QUIET)

file(GLOB TETHYS_NATIVE_SOURCES CONFIGURE_DEPENDS
    "${CMAKE_CURRENT_SOURCE_DIR}/src/native/*.cpp"
)

if(NOT TETHYS_NATIVE_SOURCES)
    message(STATUS "No C++ sources found in src/native; Python-only build remains available")
    message(STATUS "Add .cpp files to src/native to enable the pybind11 module")
    return()
endif()

if(NOT pybind11_FOUND)
    message(FATAL_ERROR
        "pybind11 CMake package was not found. Install pybind11 in the active Python environment."
    )
endif()

pybind11_add_module(_tethys_native MODULE ${TETHYS_NATIVE_SOURCES})
target_compile_features(_tethys_native PRIVATE cxx_std_17)
target_compile_definitions(_tethys_native PRIVATE TETHYS_NATIVE_BUILD=1)

set_target_properties(_tethys_native PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/src/wuwa_calculator/native"
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/src/wuwa_calculator/native"
)
