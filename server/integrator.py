import time
import logging
import numpy as np
from scipy.spatial.transform import Rotation as R
from PoseMessage_pb2 import PoseMessage
import open3d as o3d


# from D400 to T265
# H_t265_d400 = np.array([
#     [0.999968402, -0.006753626, -0.004188075, -0.015890727],
#     [0.999968402, -0.006753626, -0.004188075, -0.015890727],
#     [-0.006685408, -0.999848172, 0.016093893, 0.028273059],
#     [-0.004296131, -0.016065384, -0.999861654, -0.009375589]])

# D435 to T265
H_t265_d400 = np.array([
    [1, 0, 0, 0],
    [0, -1.0, 0, 0],
    [0, 0, -1.0, 0],
    [0, 0, 0, 1]])


H_t265_d400_r = R.from_matrix(H_t265_d400[:3,:3])

class Integrator(object):
    def __init__(self, n_poses=100, all_points=[]):
        self.poses = []
        self.all_points = all_points

        self.n_poses = n_poses
        self.current_point_idx = 0

        self.current_pose:PoseMessage = None

    def new_pose(self, pose):
        self.poses.append(pose)
        self.current_pose = pose
        if len(self.poses) > self.n_poses:
            self.poses.pop(0)

    def new_pc(self, pc_np, colors=None, rotate=True, hardware_ts=None, voxel_size=0.01):
        
        pose = self.current_pose
        # print(pose.rotation)
        if rotate and pose is not None:
            r = R.from_quat([pose.rotation.x, pose.rotation.y, pose.rotation.z, pose.rotation.w])
            pc_np = H_t265_d400_r.apply(pc_np)
            t = pose.translation
            pc_np = r.apply(pc_np)
            pc_np = pc_np + [t.x, t.y, t.z]
        
        # create o3d point cloud and downsample
        t0 = time.time()
        pc = o3d.geometry.PointCloud()
        pc.points = o3d.utility.Vector3dVector(pc_np)
        if colors is not None:
            pc.colors = o3d.utility.Vector3dVector(colors)
            # print("setting color")
        t1 = time.time()
        pcd = pc if voxel_size is None else pc.voxel_down_sample(voxel_size=voxel_size)
        t2 = time.time()

        logging.info("Create o3d Point Cloud: %.3fms; Downsample: %.3fms; %d -> %d", (t1-t0) * 1000, (t2-t1) * 1000, pc_np.shape[0], np.asarray(pcd.points).shape[0])

        # get oldest point cloud
        old_pcd = self.all_points[self.current_point_idx]
        # reset points
        old_pcd.points = pcd.points
        if colors is not None:
            old_pcd.colors = pcd.colors

        # increment point index for oldest point cloud
        self.current_point_idx += 1
        if self.current_point_idx >= len(self.all_points):
            self.current_point_idx = 0

            
        return old_pcd


        