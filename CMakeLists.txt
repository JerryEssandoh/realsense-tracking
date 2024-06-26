cmake_minimum_required(VERSION 3.14)

# Project Details
set(PROJECT_NAME "RoboEnv")
set(PROJECT_VERSION 1.0.0)

# Set Project Properties
project(${PROJECT_NAME} VERSION ${PROJECT_VERSION}
DESCRIPTION "Robotic Environment: RealSense, ECAL, OpenCV, etc." LANGUAGES CXX)

# Set Global Properties of Compiler
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
set(CMAKE_CXX_EXTENSIONS OFF)
# add_definitions(-DNDEBUG)

set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O3 -std=c++17 -Wno-narrowing -Wno-register -fPIC -g")
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS}")
# set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -mtune=native -march=native") # beware eigen has issues when shared libraries are compiled with different optimization levels!!!!!
set(CMAKE_BUILD_TYPE "Release")


# Add any "git cloned" dependencies needed by our project. They will be declared in "thridparty" directory
add_subdirectory("thirdparty")

# Add any dependencies that have been installed into standard default locations (e.g., /usr/local/lib)
# These dependencies should have been installed by Docker (`Docker/base/Dockerfile`)
# Or by the user by following the Dockerfile
find_package(OpenCV REQUIRED)
find_package(OpenMP)
find_package(realsense2 REQUIRED)
find_package(Protobuf REQUIRED)
find_package(eCAL COMPONENTS core REQUIRED)
find_package(OpenGL)
find_package(gflags REQUIRED)
set(glog_DIR /opt/workspace/dk-x86_64-build/glog/build) #Set path for GLOG. Installation must be done ahead of time!
find_package(glog REQUIRED PATHS ${CMAKE_SOURCE_DIR}/third_party/glog NO_DEFAULT_PATH)# Now Ubuntu should be able to find it.
find_package(Eigen3 REQUIRED )
find_package(Open3D HINTS ${CMAKE_INSTALL_PREFIX}/lib/CMake REQUIRED)

# Protobuff Generation
set(PROTO_DIR "${PROJECT_SOURCE_DIR}/proto")
set(PROTO_FILES ${PROTO_DIR}/Common.proto  ${PROTO_DIR}/ImageMessage.proto 
                ${PROTO_DIR}/PointCloudMessage.proto  ${PROTO_DIR}/IMUMessage.proto 
                ${PROTO_DIR}/PoseMessage.proto ${PROTO_DIR}/Integrate.proto
                ${PROTO_DIR}/LandingMessage.proto ${PROTO_DIR}/TouchdownMessage.proto)

PROTOBUF_GENERATE_CPP(PROTO_SRCS PROTO_HDRS ${PROTO_FILES})
protobuf_generate_python(PY_SOURCES ${PROTO_FILES})
# Print path to generated files
message ("PROTO_SRCS = ${PROTO_SRCS}")
message ("PROTO_HDRS = ${PROTO_HDRS}")

# Set the output directories of cmake
set(CMAKE_RUNTIME_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/bin/${CMAKE_HOST_SYSTEM_PROCESSOR})
set(CMAKE_LIBRARY_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/lib/${CMAKE_HOST_SYSTEM_PROCESSOR})
set(CMAKE_ARCHIVE_OUTPUT_DIRECTORY ${CMAKE_SOURCE_DIR}/lib/${CMAKE_HOST_SYSTEM_PROCESSOR})

message ("CMAKE_INSTALL_PREFIX = ${CMAKE_INSTALL_PREFIX}")
message ("eigen_include_dirs = ${eigen_include_dirs}")
message ("CMAKE_LIBRARY_OUTPUT_DIRECTORY = ${CMAKE_LIBRARY_OUTPUT_DIRECTORY}")
message ("CMAKE_ARCHIVE_OUTPUT_DIRECTORY = ${CMAKE_ARCHIVE_OUTPUT_DIRECTORY}")
message ("Open3D_INCLUDE_DIRS = ${Open3D_INCLUDE_DIRS}")

# Set all the dependencies
set(DEPENDENCIES glfw realsense2-gl ${realsense2_LIBRARY} ${OPENGL_LIBRARIES} ${DEPENDENCIES} ${PROTOBUF_LIBRARIES} 
${Open3D_LIBRARIES} ${OpenCV_LIBRARIES} OpenMP::OpenMP_CXX gflags glog eCAL::core) 

# Add the application sources to the target
# add_executable(rs-motion-2 src/rs-motion-2.cpp)
# add_executable(rs-test src/rs-test.cpp src/utility.cpp ${PROTO_SRCS} ${PROTO_HDRS})
# target_link_libraries(rs-motion-2 ${realsense2_LIBRARY} ${DEPENDENCIES})
# target_link_libraries(rs-test ${realsense2_LIBRARY} ${DEPENDENCIES}) 

# Create Object library, these utility files are used for each exectuable
add_library(rs-util OBJECT src/utility.cpp ${PROTO_SRCS})
# Create the executables
add_executable(rs-pub src/rs-pub.cpp ${PROTO_HDRS})
add_executable(rs-save src/rs-save.cpp ${PROTO_HDRS})
add_executable(rs-integrate-server src/rs-integrate-server.cpp ${PROTO_HDRS})

# Link the Libraries
target_link_libraries(rs-pub PUBLIC ${DEPENDENCIES} rs-util)
target_link_libraries(rs-save PUBLIC ${DEPENDENCIES} rs-util)
target_link_libraries(rs-integrate-server PUBLIC ${DEPENDENCIES} rs-util)

# Set the include directories
set(CMAKE_BUILD_INCLUDE_DIRECTORY ${CMAKE_CURRENT_BINARY_DIR})
set(INCLUDE_DIRS_ALL 
    ${PROJECT_SOURCE_DIR}/src/include
    ${PROJECT_SOURCE_DIR}/thirdparty/toml11
    /usr/include
    /usr/local/include
    /usr/local/include/opencv2
    ${CMAKE_BUILD_INCLUDE_DIRECTORY}
    ${PROJECT_SOURCE_DIR}/../librealsense/common/res
    ${PROJECT_SOURCE_DIR}/../librealsense/src
    ${PROTOBUF_INCLUDE_DIRS}
    ${GFLAG_INCLUDE_DIRS}
    # ${toml11_SOURCE_DIR}
    ${Open3D_INCLUDE_DIRS}
    ${EIGEN3_INCLUDE_DIR}
) 

target_include_directories(rs-util PUBLIC
    ${INCLUDE_DIRS_ALL}
)

target_include_directories(rs-pub PUBLIC
    ${INCLUDE_DIRS_ALL}
)

target_include_directories(rs-save PUBLIC
    ${INCLUDE_DIRS_ALL}
)

target_include_directories(rs-integrate-server PUBLIC
    ${INCLUDE_DIRS_ALL}
)

target_include_directories(rs-pub SYSTEM PUBLIC ${eigen_include_dirs})
target_include_directories(rs-save SYSTEM PUBLIC ${eigen_include_dirs})
target_include_directories(rs-integrate-server SYSTEM PUBLIC ${eigen_include_dirs})
# Must have this dummy target for the python generated sources by Probobuff CMake.
add_custom_target(DUMMY_TARGET ALL 
                  DEPENDS ${PY_SOURCES})
