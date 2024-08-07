
# RealSense Robotic Modules

The purpose of this repository is to provide a reproducible (possibly isolated) environment for high level robotics software. Currently the main concern of this repo is interacting with Intel RealSense Cameras.  This environment (code of this repo) can be be distributed as a docker image that is cross-compiled to both x86-64 and arm64 architectures (Regular computers as well as raspberry pi). Here is a quick list of thing this repository is meant to do:

- Have a stable pre-setup ubuntu environment in a docker image with all installed dependencies. 
- Communicate with Intel RealSense Devices using librealsense SDK 2.0.
- Provide a communication framework using [ECAL](https://github.com/continental/ecal) which provides efficient shared memory to publish "messages".
- Provide simple configurations file that can configure publishing of realsense cameras and saving data.
  - See `rspub_default.toml` for publishing and `rssave_default.toml` for saving RealSense data.
- Provide Python client code for visualizing mesh creation.

## Install Libraries and Dependencies

All dependencies and installation procedures can be found in `Docker/base/Dockerfile`. You can use docker and have everything taken care or you can follow the installation procedures in the file. Here is a basic summary of the environment:

- Ubuntu Base Image 20.04
- Python 3 w/ Scipy, numpy
- CMake 3.29.6 - Needed because realsense asks for 3.11 or higher.
- Open CV 3.4.16 with user contributed modules
- ECAL for marshalling and communication
- Protobuf - Serialization format (Thinking of changing to Flatbuffers eventually)
- RealSense SDK
- Open3D - new point cloud and mesh processing library from Intel
- GFLAGS and GLOG for command line parsing and logging

### Local Install

If you want to install locally please execute the following scripts (there will need to be some adjustments for you environment)

0. `./Docker/base/dependencies_local.sh`
1. `./Docker/base/ecal_local.sh`
2. `./Docker/base/opencv_local.sh`
3. `./Docker/base/realsense_local.sh` - Uses RSUSB backend, not kernel


## Setup ECAL

This is only required if you want two computers on the same network to talk to each other.

1. Update each computers hosts file so that they are aware of each other. An example below. Don't forget the `.localdomain`.

Example:
```txt
127.0.0.1       localhost
::1             localhost
127.0.1.1       cerberus.localdomain    cerberus
192.168.1.3     raspberrypi

```

2. Configure Multicast for device - `ifconfig YOUR_NETWORK_DEVICE multicast` 
3. Add Multicast route - `sudo route add -net 224.0.0.0 netmask 255.0.0.0 dev YOUR_NETWORK_DEVICE`

Note that I am using the **non-default** multi-cast group `224.0.0.0` for ecal because my router was for some reason blocking the default.

When having any problems first see these issues: [Issue 1](`https://github.com/continental/ecal/issues/38`), [Issue 2](https://github.com/continental/ecal/issues/37)

### ECAL Config File

The software is configured to use the `config/ecal/ecal.ini` file. Note that some values have been changed from the default. If you are using `ecal_mon_gui` on an  external computer to monitor messages dont forget to modify *your* `ecal.ini` to point to the correct UDP multicast address and other options (e.g., `ttl`).

## Run Docker

### X86 Linux

1. [Install Docker](https://docs.docker.com/get-docker/)
2. `git clone --recursive https://github.com/JeremyBYU/realsense-tracking.git && cd realsense-tracking`

### Raspberry PI 4

A raspberry pi image has already been created and set up. Download the image and flash the sd card.

uname: a2sys

password: a2sysblah

1. `ssh -X a2sys@192.168.1.25` - Allows XForwarding if needed. Might need to use gui (hdmi) to find out what the ip is first. IP subject to change for your own network.
2. `cd $HOME/Documents/realsense-tracking`

### Launch Docker

1. `rs-pose`, `rs-enumerate-devices` - Need to "open" the sensors on host first before launching docker. Not sure why.
2. `docker run  --rm --privileged -it --env="DISPLAY" --net=host --volume="/tmp/.X11-unix:/tmp/.X11-unix:rw" --mount type=bind,source="$(pwd)",target=/opt/workspace --name realsense jeremybyu/realsense:buildx` - Raspberry PI
3. Optional - `rm -rf build && mkdir build && cd build && cmake .. && make && cd ..`

Alternative X86 Launch - `docker run  --rm --privileged -it --env="DISPLAY" --net=host --volume="/tmp/.X11-unix:/tmp/.X11-unix:rw" --mount type=bind,source="$(pwd)",target=/opt/workspace --name realsense --user $(id -u):$(id -g) --ipc=host jeremybyu/landing:latest`


Also see `Docker/README.md` for building and launching.

## Run Locally

Install all dependencies and simply `cd` to `realsense-tracking`


## Build Applications

Make a cmake `build` directory. I use:

* `cmake-build` for local development. No docker.
* `dk-x86_64-build` for x86 Docker development. On your local computer, inside docker x86 container, building application.
* `dk-aarch64-build` for arm Docker development. On your local computer, inside docker arm container (using QEMU underneath), building application.

0. If using docker, enter into terminal shell
1. `mkdir MY_BUILD_DIR && cd MY_BUILD_DIR`
2. `cmake .. && cmake --build -j8`
3. `cmake --build MY_BUILD_DIR` Don't forget this step, you're cooked otherwise lol. You  also need to cd out of the build directory.


## Applications

All log files should be saved in the `logs` directory. Simply add `--log_dir=./logs` to command line of any application below.
You can view the log files with: `less +F logs/rs-pub.INFO`
Your can clear log files with: `./scripts/misc/clear_logs.sh`

### RS-Pub

Will publish topics which are configured in a toml file. Configured by `config/rspub_default.toml`.

1. `GLOG_logtostderr=1 ./bin/rs-pub`

`./bin/x86_64/rs-pub --log_dir=./logs --v=1 --config=config/l515/rspub_default.toml` 

`--force_udp` is an option

### RS-Save

Will Subscribe to topics and Save data to disk. Configured by `config/rssave_default.toml`.

1. `GLOG_logtostderr=1 ./bin/rs-save --config=config/rssave_default.toml`

### RS-Proto-Folder

Will convert saved protofiles in a folder to text format. This is for any point clouds or pose information.

1. `python scripts/rs-proto-folder.py`

### RS-Integrate-Server

Creates an RPC Server that allows users to generate meshes on demand with simple requests. This requires both the T265 Poses and D4XX RGBD frames to be published.
It will automatically subscribe to RGBD Images and integrate them to a voxel volume. Users can (on demand) request
to extract meshes from the voxel volume. Configured by `config/rsintegrate_default.toml`.

1. `export OMP_NUM_THREADS=1` - Multithreading actually screws this worse!
2. `GLOG_logtostderr=1 ./bin/rs-integrate-server --v=1`


## Notes

### Serial Emulation

0. https://stackoverflow.com/a/19733677
1. Enter this into terminal 1 `socat -d -d pty,raw,echo=0 pty,raw,echo=0`
2. Now `/dev/pts/1` and `/dev/pts/2` are linked. Tested with writing to `/dev/pts/2` and reading from `/dev/pts/1`

### Deploy Binaries instead of Docker

Instead of *deploying* a docker image, you can just deploy the binaries it built! The following script will gather all the dependencies for the binary in the `bin/$ARCH` folder.
You must be inside the docker container when executing this script

1. `./scripts/dependencies/gather_all.sh`

You can launch the binaries in parallel with this command: `parallel --verbose --linebuffer ::: scripts/launch/launch_rspub.sh scripts/launch/launch_integrate.sh`


#### X86_64

1. `export LD_LIBRARY_PATH=./bin/x86_64`
2. `GLOG_logtostderr=1 ./bin/x86_64/ld-linux-x86-64.so.2 ./bin/rs-pub --help`.

#### aarch64

A couple of caveats when running binaries in your envrionment: If you are using raspbian and have the 64bit kernel mode enabled then you [must use the loader](https://siddhesh.in/posts/changing-the-default-loader-for-a-program-in-its-elf.html) in the dependencies folder to launch the program. Basically

1. `export LD_LIBRARY_PATH=./bin/aarch64`
2. `GLOG_logtostderr=1 ./bin/aarch64/ld-linux-aarch64.so.1  ./bin/rs-pub --help`.

Just tested this on ARM and it actually worked! The only thing that was missing was `libecaltime-localtime.so`.


### Save Docker Images (no DokcerHub needed)

You can save a docker image to a file as so:
docker save -o <path for generated tar file> <image name>
docker save -o docker_images/roboenv.tar jeremybyu/realsense:latest

You can load a docker image as so:
docker load -i roboenv.tar

### RPI SSH

#### Copy Saved Mesh File

1. `scp pi@192.168.1.3:/home/pi/Documents/realsense-tracking/data/Default.ply data/Default.ply`


### Trim Down Image

The image is 3.1 GB.  Open3D is about 1.1 GB! 475 MB of that is the python installs from extension (338 MB is just the `open3d.so` file). Maybe get rid of it?

[Helpful Reseouce](https://towardsdatascience.com/slimming-down-your-docker-images-275f0ca9337e)

```txt
Cmp   Size  Command                                                                                  Permission     UID:GID       Size  Filetree
     63 MB  FROM d9bd0dcaa40bc11                                                                     drwx------         0:0      41 MB  ├── root                                                        
    988 kB  [ -z "$(apt-get indextargets)" ]                                                         drwx------         0:0      41 MB  │   └── .cache                                                  
     745 B  set -xe   && echo '#!/bin/sh' > /usr/sbin/policy-rc.d  && echo 'exit 101' >> /usr/sbin/p drwx------         0:0      41 MB  │       └─⊕ pip                                                 
       7 B  mkdir -p /run/systemd && echo 'docker' > /run/systemd/container                          drwxr-xr-x         0:0     1.1 GB  └── usr                                                         
    3.2 MB  echo 'Etc/UTC' > /etc/timezone &&     ln -s /usr/share/zoneinfo/Etc/UTC /etc/localtime & drwxr-xr-x         0:0     1.1 GB      └── local                                                   
    446 MB  apt-get update && apt-get install -q -y     bash-completion     lsb-release     python3- drwxr-xr-x         0:0     5.3 kB          ├─⊕ bin                                                 
       0 B  #(nop) WORKDIR /opt/workspace                                                            drwxr-xr-x         0:0      140 B          ├─⊕ etc                                                 
    322 MB  apt-get update &&     apt-get install -q -y wget git libssl-dev libusb-1.0-0-dev pkg-con drwxr-xr-x         0:0      13 MB          ├─⊕ include                                             
    156 MB  apt-get install --no-install-recommends -y build-essential libgtk2.0-dev pkg-config liba drwxr-xr-x         0:0     1.1 GB          ├── lib                                                 
     48 MB  apt-get install --no-install-recommends -y graphviz build-essential zlib1g-dev libhdf5-d drwxr-xr-x         0:0     3.0 kB          │   ├─⊕ cmake                                           
     67 MB  wget -O /opt/cmake-3.15.5.tar.gz https://cmake.org/files/v3.15/cmake-3.15.5.tar.gz &&    -rw-r--r--         0:0     597 MB          │   ├── libOpen3D.a                                     
     745 B  #(nop) COPY file:03028ab537c33176c2c9827484d3abff128258e6c117cf751ff343c7b0df99dc in /tm -rw-r--r--         0:0     4.7 MB          │   ├── libjsoncpp.a                                    
     745 B  chmod u+x /tmp/opencv.sh                                                                 -rw-r--r--         0:0     5.6 MB          │   ├── libqhullcpp.a                                   
    192 MB  git clone -b '3.4.7' --single-branch https://github.com/opencv/opencv.git /opt/opencv && -rw-r--r--         0:0     2.3 MB          │   ├── libqhullstatic_r.a                              
     40 MB  cd /opt &&     git clone --recursive git://github.com/continental/ecal.git &&     cd eca -rw-r--r--         0:0     854 kB          │   ├── libtinyfiledialogs.a                            
    395 MB  git clone https://github.com/IntelRealSense/librealsense.git /opt/librealsense && cd /op -rw-r--r--         0:0     3.1 MB          │   ├── libtinyobjloader.a                              
       0 B  ln -s /usr/bin/python3 /usr/bin/python &     ln -s /usr/bin/pip3 /usr/bin/pip            -rw-r--r--         0:0     765 kB          │   ├── libturbojpeg.a                                  
    1.2 GB  cd /opt && git clone --recursive https://github.com/intel-isl/Open3D &&     cd /opt/Open drwxrwxr-x        0:50     495 MB          │   └── python3.6                                       
    3.4 MB  apt-get install --no-install-recommends -y nano htop                                     drwxrwxr-x        0:50     495 MB          │       └─⊕ dist-packages                               
     32 MB  apt-get install --no-install-recommends -y libgflags-dev libgoogle-glog-dev gfortran     drwxr-xr-x         0:0     4.6 MB          └─⊕ share   

```
## Modern Issues 
Here is a collection of some of the fixes I've implemented in running this repo in the year 2024. 
### Prevent Compilation Errors During Build
There are a couple of things to keep note of regarding appyling the software here to run between systems. To prevent compilation errors due to full memory, you must adjust the number of jobs to match (or go under) the available threads for the machine.
Essentially, 'ARG N_CPUS=' is the number that must be adjusted. You can also have adjust the make statement at each step 'make j__' to adjust the number of threads used.

### GLOG Fix
Glog can be required during the CMAKE steps of the build! You just need to install it beforehand (add installation steps here in a bit) and then set the path to look for the built GLOG information. Works perfectly, but you can also just run the orignial code as is if you would like.

### Open 3D Note
Update the version used to v0.13.0 if choosing to build with Docker. It won't work with v0.12.0, and the patch file won't break if it's done.
### credStore
This is an awful bug that happens when you run the Dockerfile, occasionally. 
