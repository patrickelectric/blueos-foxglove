import json
import logging
import foxglove
import re
from foxglove import Channel
from foxglove.channels import LocationFixChannel, LogChannel
from foxglove.schemas import LocationFix, Log, LogLevel, Timestamp
from foxglove.websocket import Capability
import zenoh
from zenoh import Session, Sample

# Configure logging
logger = logging.getLogger("foxglove_bridge")

class Bridge:
    def __init__(self):
        self.location_fix_channel = LocationFixChannel("vehicle/position")
        self.mavlink_channels = {}
        self.service_channels = {}
        self.session = None
        self.server = None

    async def start(self):
        # Start Foxglove server
        self.server = foxglove.start_server(
            name="mavlink_server",
            capabilities=[Capability.ClientPublish],
            host="0.0.0.0",
            port=8765
        )
        logger.info("Foxglove server started at ws://0.0.0.0:8765")

        # Initialize Zenoh session
        conf = zenoh.Config()
        conf.insert_json5("mode", '"peer"')
        self.session = zenoh.open(conf)

        # Set up single subscriber for all topics
        self.session.declare_subscriber("**", self.message_callback)

    def message_callback(self, sample: Sample):
        try:
            topic = str(sample.key_expr)

            # Match mavlink topics
            if re.match(r"mavlink/1/1/.*", topic):
                self._handle_mavlink_message(sample)
            # Match service log topics
            elif re.match(r"services/.*/log", topic):
                self._handle_service_log(sample)
            else:
                logger.info(f"Unknown topic: {topic}")

        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def _handle_mavlink_message(self, sample: Sample):
        try:
            payload_bytes = bytes(sample.payload)
            try:
                data = json.loads(payload_bytes.decode('utf-8'))
            except json.JSONDecodeError:
                return

            if not isinstance(data, dict) or "message" not in data:
                return

            msg = data["message"]
            if "type" not in msg:
                return

            msg_type = msg["type"]
            topic = f"mavlink/1/1/{msg_type}"

            if topic not in self.mavlink_channels:
                self.mavlink_channels[topic] = Channel(topic, message_encoding="json")

            # Send message
            self.mavlink_channels[topic].log(data)

            if msg_type == "GLOBAL_POSITION_INT":
                location_fix = LocationFix(
                    frame_id="map",
                    latitude=msg["lat"] / 1e7,  # Convert to degrees
                    longitude=msg["lon"] / 1e7,  # Convert to degrees
                    altitude=msg["alt"] / 1000.0,  # Convert to meters
                )
                self.location_fix_channel.log(location_fix)

        except Exception as e:
            logger.error(f"Error processing mavlink message: {e}")

    def _handle_service_log(self, sample: Sample):
        try:
            payload_bytes = bytes(sample.payload)
            try:
                data = json.loads(payload_bytes.decode('utf-8'))
            except json.JSONDecodeError:
                return

            if not isinstance(data, dict):
                return

            topic = str(sample.key_expr)

            if topic not in self.service_channels:
                self.service_channels[topic] = LogChannel(topic)

            # Create a switch case for each number and log the message
            match data["level"]:
                case 0:
                    level = LogLevel.Unknown
                case 1:
                    level = LogLevel.Debug
                case 2:
                    level = LogLevel.Info
                case 3:
                    level = LogLevel.Warning
                case 4:
                    level = LogLevel.Error
                case 5:
                    level = LogLevel.Fatal
                case _:
                    level = LogLevel.Unknown

            log_msg = Log(
                level=level,
                message=data["message"],
                name=data["name"],
                file=data["file"],
                line=data["line"],
                timestamp=Timestamp(sec=int(data["timestamp"]["sec"]), nsec=int(data["timestamp"]["nsec"])),
            )
            self.service_channels[topic].log(log_msg)

        except Exception as e:
            logger.error(f"Error processing service log: {e}")

    def cleanup(self):
        if self.session:
            self.session.close()