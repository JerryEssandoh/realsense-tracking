ARG N_CPUS = 4 
FROM jeremybyu/realsense:latest
ARG N_CPUS

# This is needed from before, just in case environment variabled didn't carry forth from jeremybyu/realsense
ENV PYTHONPATH $PYTHONPATH:/usr/local/lib

# install packages
RUN apt-get update && apt-get install -q -y \
    python3-shapely \
    python3-tk \
    parallel \
    python3-matplotlib

RUN apt-get -q -y purge python3-scipy

RUN pip install toml pyyaml numpy
RUN pip install --upgrade numpy
RUN pip install scipy
RUN pip install open3d==0.13.0
RUN pip install py_cui ipdb

# Clone Polylidar3D
RUN git clone -b 'landing' --single-branch --recursive https://github.com/JeremyBYU/polylidar.git /opt/polylidar && \
    cd /opt/polylidar && mkdir cmake-build && cd cmake-build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release -DFETCHCONTENT_QUIET=OFF && \
    make -j${N_CPUS} && \
    cmake --build . --target python-package --config Release -j${N_CPUS} && \
    cd lib/python_package && pip install . && \
    rm -rf /opt/polylidar

# Clone FastGaussianAccumulator
RUN git clone -b 'master' --single-branch --recursive https://github.com/JeremyBYU/FastGaussianAccumulator.git /opt/fastgac && \
    cd /opt/fastgac && mkdir cmake-build && cd cmake-build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_FLAGS="-O3 -DNDEBUG -msse4.2" -DFETCHCONTENT_QUIET=OFF && \
    make -j${N_CPUS} && \
    cmake --build . --target python-package --config Release -j${N_CPUS} && \
    cd lib/python_package && pip install . && \
    rm -rf /opt/fastgac

# Clone OrganizedPointFilters
RUN git clone --recursive https://github.com/JeremyBYU/OrganizedPointFilters.git /opt/opf && \
    cd /opt/opf && mkdir cmake-build && cd cmake-build && \
    cmake .. -DCMAKE_BUILD_TYPE=Release -DFETCHCONTENT_QUIET=OFF && \
    make -j${N_CPUS} && \
    cmake --build . --target python-package --config Release -j${N_CPUS} && \
    cd lib/python_package && pip install . && \
    rm -rf /opt/opf

RUN pip install multiprocessing-logging pyserial
# Polylabel Fast
RUN git clone --recursive https://github.com/JeremyBYU/polylabelfast.git /opt/polylabelfast && \
    cd /opt/polylabelfast && pip install . && \
    rm -rf /opt/polylabelfast


CMD ["bash"]
