import sys
import time
from multiprocessing import Process, Lock, Queue, Manager
import multiprocessing
import queue
# from multiprocessing.managers import SyncManager, MakeProxyType, public_methods, BaseProxy
import numpy as np
import matplotlib.pyplot as plt
from landing.helper.helper_logging import setup_logger
logger = setup_logger()
import open3d as o3d
from scipy.spatial.transform import Rotation as R
import serial

import ecal.core.core as ecal_core
import ecal.core.service as ecal_service
from ecal.core.service import Client
from ecal.core.subscriber import ProtoSubscriber
from ecal.core.publisher import ProtoPublisher

from PoseMessage_pb2 import PoseMessage
from ImageMessage_pb2 import ImageMessage
from LandingMessage_pb2 import LandingMessage
from Integrate_pb2 import IntegrateRequest, IntegrateResponse, ExtractResponse, ExtractRequest, START, STOP, MESH, Mesh
from TouchdownMessage_pb2 import TouchdownMessage, MeshAndTouchdownMessage


from polylidar import Polylidar3D, MatrixDouble, MatrixFloat, extract_point_cloud_from_float_depth, bilateral_filter_normals
from fastgac import GaussianAccumulatorS2Beta, IcoCharts
from landing.helper.helper_polylidar import extract_polygons_from_points, get_3D_touchdown_point, extract_polygons_from_tri_mesh
from landing.helper.helper_utility import create_projection_matrix, create_transform, create_proto_vec, get_mesh_data_from_message, create_touchdown_message
from landing.helper.o3d_util import create_o3d_pc, create_linemesh_from_shapely, get_segments
from landing.helper.helper_meshes import create_o3d_mesh_from_tri_mesh, create_o3d_mesh_from_data, create_tri_mesh_from_data
from landing.helper.helper_vis import plot_polygons
from landing.serial.common import serialize, MessagePoseUpdate, MessageLandingCommand, get_us_from_epoch


BLUE = (255, 0, 0)


class LandingService(object):
    def __init__(self, config):
        # This is our configuration variable, holds all parameters
        self.config = config
        # A simple frame counter
        self.frame_count = 0
        self.pose_translation_ned = None
        self.pose_rotation_ned = None

        # Single Scan Variables
        self.active_single_scan = False
        # Integration Variables
        self.active_integration = False
        self.completed_integration = False
        self.extracted_mesh_message = None
        self.integrated_touchdown_point = None
        self.integrated_touchdown_dist = None
        self.integrated_touchdown_result = None
        self.integrated_tri_mesh = None

        # All single scans will be recorded (appended to list) from a separate process
        self.manager = Manager()  # manages shared data between polylidar process
        # These will contain the results of all single scan touchdowns points
        self.single_scan_touchdowns = self.manager.list()  # Lock is implicit when accessing between processes
        # These will contain the results of all integrated touchdown points

        # Will set up serial communications
        cfg = self.config['serial']
        self.serial = serial.Serial(cfg['port'], cfg['baudrate'], timeout=cfg['timeout'])
        self.serial_lock = Lock()
        self.message_pose_update = MessagePoseUpdate()
        self.message_landing_command = MessageLandingCommand()
        # Will set up all frames and fixed transformations
        self.setup_frames()
        # Wil set up ECAL communication
        self.setup_ecal()

    def callback_pose(self, topic_name, pose: PoseMessage, time_):
        # logger.info(f"Pose of T265 in T265 World Frame: translation: {vec3_to_str(pose.translation)}; \
        #                 rotation (deg): {np_to_str(t265_rot)}; Pose HTS: {pose.hardware_ts:.2f}; Pose RTS: {time_/1000:.2f}")
        try:
            # position and rotation of t265 in "t265 axis world frame" # see readme for definitions
            H_t265_w_t265 = create_transform([pose.translation.x, pose.translation.y, pose.translation.z],
                                             [pose.rotation.x, pose.rotation.y, pose.rotation.z, pose.rotation.w])
            t265_rot = R.from_matrix(H_t265_w_t265[:3, :3]).as_euler('xyz', degrees=True)
            logger.debug(
                f"Pose of T265 in T265 World Frame: translation: {vec3_to_str(pose.translation)}; rotation (deg): {np_to_str(t265_rot)}")

            # Transforms T265 frame to the center of drone body. Axis frame is still t265 (as if if you moved the T265 camera)
            H_body_w_t265 = H_t265_w_t265 @ self.body_frame_transform_in_t265_frame
            body_rot = R.from_matrix(H_body_w_t265[:3, :3]).as_euler('xyz', degrees=True)
            logger.debug(
                f"Pose of Body in T265 World Frame: translation: {np_to_str(H_body_w_t265[:3, 3])}; rotation (deg): {np_to_str(body_rot)};")
            # convert t265 axis world frame to ned world frame
            # Robot Modelling and Control, Spong, Similarity Transform 2.3.1, Page 41
            H_body_w_ned = self.t265_world_to_ned_world @ H_body_w_t265 @ np.linalg.inv(self.t265_world_to_ned_world)
            ned_rot = R.from_matrix(H_body_w_ned[:3, :3]).as_euler('xyz', degrees=True)
            ned_rot_quat = R.from_matrix(H_body_w_ned[:3, :3]).as_quat().flatten().tolist()
            logger.debug(
                f"Pose of Body in NED World Frame: translation: {np_to_str(H_body_w_ned[:3, 3])}; rotation (deg): {np_to_str(ned_rot)}")

            # The ORIGIN of this world NED frame is at center of the T265
            # The axes are NED, where X axis where the drone was intially pointed at time t=0
            # These means the drone position at time t=0 will be a few (10?) centimeters off in x-axis
            self.pose_translation_ned = H_body_w_ned[:3, 3].flatten().tolist()
            self.pose_rotation_ned = ned_rot_quat

            # Update raw ctype struct for message to be sent over serial
            self.message_pose_update.pose_update.time_us = get_us_from_epoch()
            self.message_pose_update.pose_update.x = self.pose_translation_ned[0]
            self.message_pose_update.pose_update.y = self.pose_translation_ned[1]
            self.message_pose_update.pose_update.z = self.pose_translation_ned[2]
            self.message_pose_update.pose_update.roll = ned_rot[0]
            self.message_pose_update.pose_update.pitch = ned_rot[1]
            self.message_pose_update.pose_update.yaw = ned_rot[2]

            self.send_serial_msg(self.message_pose_update)

        except Exception as e:
            logger.exception("Error!")
        pass

    def send_serial_msg(self, msg):
        msg_serialized = serialize(msg).contents.raw # This makes no copy, preferred
        self.serial_lock.acquire()
        self.serial.write(msg_serialized)
        self.serial_lock.release()

    def callback_depth(self, topic_name, image: ImageMessage, time_):
        logger.info(f"Callback Image START: {time.perf_counter() * 1000:.1f}")
        try:
            self.frame_count += 1
            if self.active_single_scan:
                self.landing_queue.put(image)
            # self.pub_image.send(image)
        except Exception as e:
            logger.exception("Error in callback depth")

    # define the server method "find_touchdown" function
    def callback_activate_single_scan_touchdown(self, method_name, req_type, resp_type, request):
        logger.info("'LandingService' method %s called with %s", method_name, request)
        # decodes bytes into utf-8 string
        request = request.decode('utf-8')
        self.active_single_scan = request == 'active'
        return 0, bytes("success", "ascii")

    def initiate_single_scan_landing(self):
        last_touchdown = self.single_scan_touchdowns[-1]
        tp = last_touchdown['touchdown_point']
        point = tp['point']
        dist = tp['dist']
        logger.info("Initiating landing at %s with %.2f radial clearance", point, dist)
        # update message
        self.message_landing_command.landing_command.time_us = get_us_from_epoch()
        self.message_landing_command.landing_command.x = point[0]
        self.message_landing_command.landing_command.y = point[1]
        self.message_landing_command.landing_command.z = point[2]
        # Send command to beaglebone
        self.send_serial_msg(self.message_landing_command)

    def initiate_integrated_landing(self):
        point = self.integrated_touchdown_point
        dist = self.integrated_touchdown_dist
        logger.info("Initiating integrated landing at %s with %.2f radial clearance", point, dist)
        self.message_landing_command.landing_command.time_us = get_us_from_epoch()
        self.message_landing_command.landing_command.x = point[0]
        self.message_landing_command.landing_command.y = point[1]
        self.message_landing_command.landing_command.z = point[2]
        # Send command to beaglebone
        self.send_serial_msg(self.message_landing_command)

    def callback_integration_service_forward(self, method_name, req_type, resp_type, this_request):
        this_request = this_request.decode('utf-8')
        request = IntegrateRequest()
        logger.info("'LandingService' method %s called with %s", method_name, this_request)

        rtn_value = 0
        rtn_msg = "success"

        request.pre_multiply.data[:] = self.integrate_pre.flatten().tolist()  # Appends an entire list
        request.post_multiply.data[:] = self.integrate_post.flatten().tolist()  # Appends an entire list

        if this_request == "integrated_start":
            if self.active_integration:
                logger.warn("Trying to start when already active...")
                rtn_value = 1
                rtn_msg = "Trying to start when already active..."
            else:
                request.type = START
                request.scene = "Default"
                request_string = request.SerializeToString()
                _ = self.integration_client.call_method("IntegrateScene", request_string)
                logger.info("Starting volume integration")
                self.active_integration = True
        elif this_request == "integrated_stop":
            if self.active_integration:
                request.type = STOP
                request.scene = "Default"
                request_string = request.SerializeToString()
                _ = self.integration_client.call_method("IntegrateScene", request_string)
                logger.info("Stopping volume integration")
                self.active_integration = False
                self.completed_integration = True
            else:
                logger.warn("Integration has not started")
                rtn_value = 1
                rtn_msg = "Integration has not started"
        elif this_request == "integrated_extract":
            if self.active_integration or self.completed_integration:
                request = ExtractRequest()
                request.scene = "Default"
                request.type = MESH
                request_string = request.SerializeToString()
                _ = self.integration_client.call_method("ExtractScene", request_string)
                logger.info("Sending request to integration server to extract mesh")
            else:
                logger.warn("Cant extract scene because integration has not started or previously been completed")
                rtn_value = 1
                rtn_msg = "Cant extract scene because integration has not started or previously been completed"
        elif this_request == "integrated_touchdown_point":
            if self.integrated_tri_mesh is not None:
                logger.info("Finding touchdown point from integrated mesh")
                success = self.find_touchdown_from_mesh(self.integrated_tri_mesh)
                if not success:
                    rtn_value = 1
                    rtn_msg = "Couldn't find the touchdown point in mesh"
            else:
                logger.warn("Cant find touchdown point in integrated scene because no mesh has been extracted")
                rtn_value = 1
                rtn_msg = "Cant find touchdown point in integrated scene because no mesh has been extracted"
        else:
            logger.warn("Do not undersand this request: %s", this_request)
            rtn_value = 1
            rtn_msg = f"Do not undersand this request: {this_request}"

        return rtn_value, bytes(rtn_msg, "ascii")

    def find_touchdown_from_mesh(self, tri_mesh):
        success = False
        # Create Polylidar Objects
        config = self.config
        pl = Polylidar3D(**config['polylidar'])
        ga = GaussianAccumulatorS2Beta(level=config['fastgac']['level'])
        ico = IcoCharts(level=config['fastgac']['level'])

        chosen_plane, alg_timings, tri_mesh, avg_peaks, _ = extract_polygons_from_tri_mesh(
            tri_mesh, pl, ga, ico, config)

        if chosen_plane is not None:
            touchdown_point = get_3D_touchdown_point(chosen_plane, config['polylabel']['precision'])
            self.integrated_touchdown_point = touchdown_point['point'].tolist()
            self.integrated_touchdown_dist = touchdown_point['dist']
            success = True

            # VISUALIZATION
            # line_meshes = create_linemesh_from_shapely(chosen_plane[0])
            # tp = o3d.geometry.TriangleMesh.create_icosahedron(0.05).translate(touchdown_point['point'])
            # # body = o3d.geometry.TriangleMesh.create_icosahedron(0.05).translate(H_body_w_ned[:3, 3])
            # o3d_mesh = create_o3d_mesh_from_tri_mesh(tri_mesh)
            # o3d.visualization.draw_geometries([o3d_mesh, tp, *get_segments(line_meshes),
            #                                    o3d.geometry.TriangleMesh.create_coordinate_frame(size=0.5)])
        else:
            touchdown_point = None
            logger.warn("Could not find a touchdown point")

        touchdown_result = dict(polygon=chosen_plane, alg_timings=alg_timings,
                                avg_peaks=avg_peaks, touchdown_point=touchdown_point)
        self.integrated_touchdown_result = touchdown_result
        tm = create_touchdown_message(touchdown_result, command_frame='ned', integrated=True)
        # TODO lock this publisher resource?
        self.pub_touchdown.send(tm)
    
        return success

    def integration_client_resp_callback(self, service_info, response):
        logger.info("Service: %s; Method: %s", service_info['service_name'], service_info['method_name'])
        m_name = service_info['method_name']
        if (m_name == 'IntegrateScene'):
            pass
        elif m_name == 'ExtractScene':
            try:
                logger.info("Receiving Mesh from integration server")
                resp = ExtractResponse()
                resp.ParseFromString(response)
                self.extracted_mesh_message = resp
                # resp.mesh.ClearField('vertices_colors') # save UDP bandwith....
                self.pub_mesh.send(resp.mesh)
                raw_data = get_mesh_data_from_message(resp.mesh)
                tri_mesh = create_tri_mesh_from_data(raw_data[0], raw_data[1])
                logger.info("Mesh has %d vertices", np.asarray(tri_mesh.vertices).shape[0])

                t1 = time.perf_counter()
                # as long as the mesh isnt too big, this is not too expensive (sub 5 ms)
                mesh_filter = self.config['mesh_integrated']['filter']
                bilateral_filter_normals(
                    tri_mesh, iterations=mesh_filter['loops_bilateral'], sigma_length=mesh_filter['sigma_length'], sigma_angle=mesh_filter['sigma_angle'])
                t2 = time.perf_counter()
                self.integrated_tri_mesh = tri_mesh
            except:
                logger.exception("Error extracting mesh")

    # define the server method "initiate_landing" function

    def callback_initiate_landing(self, method_name, req_type, resp_type, request):
        logger.info("'LandingService' method '%s' called with %s", method_name, request)
        request = request.decode('utf-8')
        rtn_value = 0
        rtn_msg = "success"

        if request == "land_single":
            if len(self.single_scan_touchdowns) > 0 and self.active_single_scan:
                logger.info("Sending touchdown request for single scans")
                # TODO send landing command
                self.initiate_single_scan_landing()
            else:
                rtn_value = 1
                rtn_msg = "Single scanning must be activated and have succeeded recently"
                logger.warn("Single scanning must be activated and have succeeded recently")
        elif request == "land_integrated":
            if self.integrated_touchdown_point is not None:
                logger.info("Sending touchdown request for integrated mesh")
                # TODO send landing command in NED frame
                self.initiate_integrated_landing()
            else:
                rtn_value = 1
                rtn_msg = "No touchdown point has been found"
                logger.warn("No touchdown point has been found")
        else:
            rtn_value = 1
            rtn_msg = "Do not undersand this request"
            logger.warn("Do not undersand this request: %s", request)

        return rtn_value, bytes(rtn_msg, "ascii")

    def callback_send_mesh(self, method_name, req_type, resp_type, this_request):
        this_request = this_request.decode('utf-8')
        logger.info("'LandingService' method %s called with %s", method_name, this_request)
        empty = MeshAndTouchdownMessage()
        if self.extracted_mesh_message:
            empty.mesh.CopyFrom(self.extracted_mesh_message.mesh)
            if self.integrated_touchdown_result:
                tm = create_touchdown_message(self.integrated_touchdown_result, command_frame='ned', integrated=True)
                empty.touchdown.CopyFrom(tm)
            msg = empty.SerializeToString()
            return 0, msg
        else:
            return 1, empty.SerializeToString()

    def setup_frames(self):

        l515_mount = self.config['frames']['l515_sensor_mount']
        l515_axes = self.config['frames']['l515_sensor_axes']
        self.l515_axes = create_transform(l515_axes['translation'], l515_axes['rotation'])
        self.l515_mount = create_transform(np.array(l515_mount['translation']), l515_mount['rotation'])
        self.l515_to_drone_body = self.l515_mount @ self.l515_axes

        t265_mount = self.config['frames']['t265_sensor_mount']
        self.t265_mount = create_transform(np.array(t265_mount['translation']), t265_mount['rotation'])
        t265_axes = self.config['frames']['t265_sensor_axes']
        self.t265_axes = create_transform(t265_axes['translation'], t265_axes['rotation'])
        self.t265_to_drone_body = self.t265_mount @ self.t265_axes

        # print(self.t265_mount)
        self.body_frame_transform_in_t265_frame = np.linalg.inv(self.t265_axes) @ self.t265_mount @ self.t265_axes
        self.body_frame_transform_in_t265_frame[:3, 3] = -self.body_frame_transform_in_t265_frame[:3, 3]

        # print()
        # print(self.body_frame_transform_in_t265_frame)
        # rotates world frame of t265 slam to world frame of drone axes
        self.t265_world_to_ned_world = self.t265_axes
        self.l515_to_t265_frame = np.linalg.inv(self.t265_to_drone_body) @ self.l515_to_drone_body

        # axes flip between t265 and l515 (camera)
        self.t265_world_to_sensor_world = np.array([
            [1.0, 0, 0, 0],
            [0, -1, 0, 0],
            [0, 0, -1, 0],
            [0, 0, 0, 1]
        ])
        # transfrom from t265 to l515 in respect to l515 frame
        l515_to_t265 = np.linalg.inv(self.t265_axes) @ np.linalg.inv(self.t265_mount) @ self.l515_mount @ self.t265_axes
        l515_to_t265[:3, 3] = -l515_to_t265[:3, 3]
                             # Sensor to NED  # Move sensor # start similarity transfrom
        self.integrate_pre = self.l515_axes @ l515_to_t265 @ self.t265_world_to_sensor_world
        self.integrate_post = np.linalg.inv(self.t265_world_to_sensor_world)

        # Note, its like this: (At the very least you need three terms on the right)
        ###############                         S I M I L A R I T Y    T R A N S F O R M
        # H_L515_TO_NED @  H_L515_T265 @  H_t265_to_sensor @ H_t265_w_t265 @ inv(H_t265_to_sensor)

    def setup_ecal(self):
        ecal_args = []
        ecal_args.append("--ecal-ini-file");
        ecal_args.append("./config/ecal/ecal.ini");
        ecal_core.initialize(ecal_args, "Landing_Server")
        # set process state
        ecal_core.set_process_state(1, 1, "Healthy")

        # create server "LandingServer"
        self.server = ecal_service.Server("LandingService")
        # Will be lots of parameters inside of the request type
        self.server.add_method_callback("ActivateSingleScanTouchdown", "string", "string",
                                        self.callback_activate_single_scan_touchdown)
        self.server.add_method_callback("InitiateLanding", "string", "string", self.callback_initiate_landing)
        self.server.add_method_callback("IntegrationServiceForward", "string", "string",
                                        self.callback_integration_service_forward)
        self.server.add_method_callback("SendMesh", "string", "Mesh",
                                        self.callback_send_mesh)

        # create subscriber for pose information and connect callback
        self.sub_pose = ProtoSubscriber("PoseMessage", PoseMessage)
        self.sub_pose.set_callback(self.callback_pose)

        # create subscriber for depth information and connect callback
        self.sub_depth = ProtoSubscriber("RGBDMessage", ImageMessage)
        self.sub_depth.set_callback(self.callback_depth)

        # create publisher for depth information and connect callback
        self.pub_image = ProtoPublisher("RGBDLandingMessage", ImageMessage)
        self.pub_landing = ProtoPublisher("LandingMessage", LandingMessage)
        self.pub_mesh = ProtoPublisher("MeshMessage", Mesh)
        self.pub_touchdown =ProtoPublisher("TouchdownMessage", TouchdownMessage)

        # Create a client for a service for integration
        self.integration_client = Client("rspub_pb.IntegrateService")
        self.integration_client.add_response_callback(self.integration_client_resp_callback)

        self.landing_queue = Queue()
        self.pub_image_queue = Queue()
        self.landing_process = Process(target=process_image, args=(
            self, self.landing_queue, self.pub_image_queue, self.single_scan_touchdowns))
        self.landing_process.daemon = True
        self.landing_process.start()        # Launch reader_proc() as a separate python proc

    def run(self):
        frame_start = time.perf_counter()

        while ecal_core.ok():
            rgbd_fps = self.frame_count / (time.perf_counter() - frame_start)
            # logger.info("RGBD FPS: %.1f", rgbd_fps)
            if (time.perf_counter() - frame_start) > 10:
                frame_start = time.perf_counter()
                self.frame_count = 0
            time.sleep(0.05)
            # Publish Image Data
            if not self.pub_image_queue.empty():
                try:
                    image, touchdown_message = self.pub_image_queue.get_nowait()
                    self.pub_image.send(image)
                    self.pub_touchdown.send(touchdown_message)
                except queue.Empty:
                    pass
                except:
                    logger.exception("Error sending...")
            lm = self.create_landing_message()
            self.pub_landing.send(lm)

        # finalize eCAL API
        ecal_core.finalize()

    def create_landing_message(self):
        lm = LandingMessage()
        lm.frame_count = self.frame_count
        lm.active_single_scan = self.active_single_scan
        lm.active_integration = self.active_integration
        if self.pose_rotation_ned:
            lm.pose_translation_ned.CopyFrom(create_proto_vec(self.pose_translation_ned))
            lm.pose_rotation_ned.CopyFrom(create_proto_vec(self.pose_rotation_ned))
        if len(self.single_scan_touchdowns) > 0:
            touchdown = self.single_scan_touchdowns[-1]
            if touchdown['touchdown_point'] is not None:
                lm.single_touchdown_point.CopyFrom(create_proto_vec(touchdown['touchdown_point']['point'].tolist()))
                lm.single_touchdown_dist = touchdown['touchdown_point']['dist']
        lm.completed_integration = self.completed_integration
        if self.extracted_mesh_message is not None:
            lm.extracted_mesh_vertices = self.extracted_mesh_message.mesh.n_vertices

        if self.integrated_touchdown_point is not None:
            lm.integrated_touchdown_point.CopyFrom(create_proto_vec(self.integrated_touchdown_point))
            lm.integrated_touchdown_dist = self.integrated_touchdown_dist

        return lm


def process_image(landing_service: LandingService, pull_queue: Queue, push_queue: Queue, single_scan_touchdowns):
    config = landing_service.config
    stride = config['mesh']['stride']

    # Create Polylidar Objects
    pl = Polylidar3D(**config['polylidar'])
    ga = GaussianAccumulatorS2Beta(level=config['fastgac']['level'])
    ico = IcoCharts(level=config['fastgac']['level'])


    while True:
        try:
            image = pull_queue.get()
            logger.info(f"Process Image START: {time.perf_counter() * 1000:.1f}")
            # logger.info("Frame Number: %s", image.frame_number)
            t1 = time.perf_counter()
            # Get numpy array from depth image
            image_depth_np = np.frombuffer(image.image_data_second, dtype=np.uint16).reshape((image.height, image.width))
            # Convert to float depth map
            image_depth_np = np.multiply(image_depth_np, landing_service.config['depth_scale'], dtype=np.float32)
            # Get intrinsics
            intrinsics = MatrixDouble(create_projection_matrix(image.fx, image.fy, image.cx, image.cy))
            # Get extrinsics for t265, in world t265 frame
            # H_t265_w_t265 represents the homogenous transformation to transform the starting t265 frame (gravity aligned, t=0, see README) to the current
            # t265 frame at current time.
            H_t265_w_t265 = create_transform([image.translation.x, image.translation.y, image.translation.z],
                                            [image.rotation.x, image.rotation.y, image.rotation.z, image.rotation.w])
            t2 = time.perf_counter()

            # body_frame_transform_in_t265_frame represents the transform (in t265 frame) to move to the drone body position
            # Its like saying what translation/rotation do I need to take move the T265 camera to be in the center of the drone, IN RESPECT to the t265 frame.
            # So a positive 2 z translation would indicate that that the drone is 2 meters BEHIND the 265 camera (z axes of t265 frame points behind it)

            # H_body_w_t265 represents the homogenous transformation from the starting t265 frame to the where the t265 would be if in the center of drone (body frame)
            H_body_w_t265 = H_t265_w_t265 @ landing_service.body_frame_transform_in_t265_frame

            # H_body_w_ned is the same transform H_body_w_t265 but in respect to a different axes convention world frame, the NED world frame
            # Must use a similarity transform here
            # Robot Modelling and Control, Spong, Similarity Transform 2.3.1, Page 41
            H_body_w_ned = landing_service.t265_world_to_ned_world @ H_body_w_t265 @ np.linalg.inv(
                landing_service.t265_world_to_ned_world)

            # Put in point cloud from sensor to drone, from drone (body) to world ned frame
            extrinsics_world_ned = H_body_w_ned @ landing_service.l515_to_drone_body
            extrinsics_world_ned_ = MatrixDouble(extrinsics_world_ned)
            extrinsics_body_frame_ = MatrixDouble(landing_service.l515_to_drone_body)  # simple body frame
            # Put in frame chosen by user
            extrinsics = extrinsics_body_frame_ if config['single_scan']['command_frame'] == 'body' else extrinsics_world_ned_
            # Create OPC
            points = extract_point_cloud_from_float_depth(MatrixFloat(
                image_depth_np), intrinsics, extrinsics, stride=stride)
            new_shape = (int(image_depth_np.shape[0] / stride), int(image_depth_np.shape[1] / stride), 3)
            opc = np.asarray(points).reshape(new_shape)  # organized point cloud (will have NaNs!)
            t3 = time.perf_counter()
            chosen_plane, alg_timings, tri_mesh, avg_peaks, _ = extract_polygons_from_points(opc, pl, ga, ico, config)

            t4 = time.perf_counter()
            image_color_np = np.frombuffer(image.image_data, dtype=np.uint8).reshape((image.height, image.width, 3))
            if chosen_plane is not None:
                plot_polygons(chosen_plane, create_projection_matrix(image.fx, image.fy, image.cx,
                                                                    image.cy), np.linalg.inv(np.array(extrinsics)), image_color_np)
                touchdown_point = get_3D_touchdown_point(chosen_plane, config['polylabel']['precision'])
                plot_polygons((touchdown_point['circle_poly'], None), create_projection_matrix(image.fx, image.fy, image.cx, image.cy),
                            np.linalg.inv(np.array(extrinsics)), image_color_np, shell_color=BLUE)
                # VISUALIZATION
                # line_meshes = create_linemesh_from_shapely(chosen_plane[0])
                # tp = o3d.geometry.TriangleMesh.create_icosahedron(0.05).translate(touchdown_point['point'] )
                # body = o3d.geometry.TriangleMesh.create_icosahedron(0.05).translate(H_body_w_ned[:3, 3])
                # o3d_mesh = create_open_3d_mesh_from_tri_mesh(tri_mesh)
                # o3d.visualization.draw_geometries([o3d_mesh, tp, body, *get_segments(line_meshes), o3d.geometry.TriangleMesh.create_coordinate_frame(size=0.5)])
                # plt.imshow(image_color_np)
                # plt.show()

            else:
                touchdown_point = None
                logger.warn("Could not find a touchdown point")
            t5 = time.perf_counter()

            # Put modified image on queue to publish message
            touchdown_results = dict(polygon=chosen_plane, alg_timings=alg_timings,
                                    avg_peaks=avg_peaks, touchdown_point=touchdown_point)
            single_scan_touchdowns.append(touchdown_results)

            image.image_data = np.ndarray.tobytes(image_color_np)
            tm = create_touchdown_message(touchdown_results, command_frame=config['single_scan']['command_frame'], integrated=False)
            push_queue.put((image, tm))

            # logger.info(f"Process Image END: {time.perf_counter() * 1000:.1f}")
        except:
            logger.exception("Erorr in polylidar process")
        # d1 = (t2 - t1) * 1000
        # d2 = (t3 - t2) * 1000
        # d3 = (t4 - t3) * 1000
        # d4 = (t5 - t4) * 1000
        # logger.info("D1: %.2f, D2: %.2f, D3: %.2f,  D4: %.2f, timings: %s", d1, d2, d3, d4, alg_timings)
        # print(f"Process thread: {len(single_scan_touchdowns)}")


def vec3_to_str(vec):
    return f"{vec.x:.1f}, {vec.y:.1f}, {vec.z:.1f}"


def np_to_str(vec):
    start = ""
    for x in vec:
        start += f"{x:.1f} "
    return start
