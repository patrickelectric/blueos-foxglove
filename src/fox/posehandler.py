
import math
from foxglove.schemas import Pose, Quaternion, Vector3, FrameTransform, Timestamp

class PoseHandler:
    attitude = None
    position = None
    velocity = None
    quaternion = None

    def get_pose(self):
        if self.attitude is not None:
            # Convert Euler angles (roll, pitch, yaw) to quaternion
            roll = self.attitude["roll"]
            # NED frame
            pitch = -self.attitude["pitch"]
            yaw = -self.attitude["yaw"]

            # Convert to quaternion using standard formula
            cy = math.cos(yaw * 0.5)
            sy = math.sin(yaw * 0.5)
            cp = math.cos(pitch * 0.5)
            sp = math.sin(pitch * 0.5)
            cr = math.cos(roll * 0.5)
            sr = math.sin(roll * 0.5)

            qw = cr * cp * cy + sr * sp * sy
            qx = sr * cp * cy - cr * sp * sy
            qy = cr * sp * cy + sr * cp * sy
            qz = cr * cp * sy - sr * sp * cy
            self.quaternion = Quaternion(x=qx, y=qy, z=qz, w=qw)
        if self.position is not None:
            pose = Pose(
                orientation=self.quaternion,
                # convert to NED frame                                            good
                position=Vector3(x=0, y=0, z=0),
            )
            return pose
        return None

    def get_frame_transform(self):
        """Create a FrameTransform from vehicle to map frame"""
        if self.quaternion is None:
            return None
        # Create timestamp
        timestamp = Timestamp(sec=int(self.position.get("timestamp", 0)), nsec=0)

        # Create frame transform from map to vehicle
        translation = Vector3(x=0.0, y=0.0, z=0.0)
        if self.position is not None:
            translation = Vector3(
                x=self.position["x"],
                y=-self.position["y"],
                z=-self.position["z"]

            )

        frame_transform = FrameTransform(
            timestamp=timestamp,
            parent_frame_id="map",
            child_frame_id="vehicle",
            translation=translation,
            rotation=self.quaternion,
        )

        return frame_transform
