import json
import logging
import foxglove
import re
import zenoh
from foxglove import Channel
from foxglove.channels import CompressedVideoChannel,LocationFixChannel, LogChannel
from foxglove.schemas import LocationFix, Log, LogLevel, Timestamp, CompressedVideo
from foxglove.websocket import Capability
from genson import SchemaBuilder
from typing import Dict, Any
from zenoh import Session, Sample

# Configure logging
logger = logging.getLogger("foxglove_bridge")

class Bridge:
    def __init__(self):
        self.location_fix_channel = LocationFixChannel("vehicle/position")
        self.mavlink_channels = {}
        self.service_channels = {}
        self.unknown_channels: Dict[str, Channel] = {}
        self.schema_builders: Dict[str, SchemaBuilder] = {}
        self.video_channels: Dict[str, CompressedVideoChannel] = {}
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
        conf.insert_json5("mode", json.dumps("client"))
        conf.insert_json5("connect/endpoints", json.dumps(["tcp/127.0.0.1:7447"]))
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
            elif re.match(r"video/.*", topic):
                self._handle_video_message(sample)
            else:
                self._handle_unknown_message(sample)

        except Exception as e:
            logger.error(f"Error processing message: {e}")

    def _handle_unknown_message(self, sample: Sample):
        try:
            topic = str(sample.key_expr)
            # the schema will change all the time, and we don't need to log it
            if topic == "mavlink/out":
                return

            payload_bytes = bytes(sample.payload)

            try:
                data = json.loads(payload_bytes.decode('utf-8'))
            except json.JSONDecodeError:
                logger.warning(f"Failed to decode JSON for topic {topic}")
                return

            if not isinstance(data, dict):
                return

            # Ignore nested mavlink messages that are not complete
            if "mavlink/" in topic and "message" not in data:
                return

            # Initialize schema builder for this topic if it doesn't exist
            if topic not in self.schema_builders:
                self.schema_builders[topic] = SchemaBuilder()
                self.schema_builders[topic].add_object(data)
                schema = self.schema_builders[topic].to_schema()

                # Create a new channel with the generated schema
                self.unknown_channels[topic] = Channel(
                    topic,
                    message_encoding="json",
                    schema=schema
                )
                logger.info(f"Created new channel for topic {topic} with schema")
            else:
                # Add the new data to the schema builder
                self.schema_builders[topic].add_object(data)
                new_schema = self.schema_builders[topic].to_schema()

                # Only create a new channel if the schema has changed
                new_schema_str = json.dumps(new_schema)
                old_schema_str = self.unknown_channels[topic].schema().data.decode('utf-8').replace("\'", "\"")
                if new_schema_str != old_schema_str:
                    logger.info(f"new schema: {new_schema_str}")
                    logger.info(f"old schema: {old_schema_str}")
                    self.unknown_channels[topic] = Channel(
                        topic,
                        message_encoding="json",
                        schema=new_schema
                    )
                    logger.info(f"Updated channel for topic {topic} with new schema")

            # Send the message
            self.unknown_channels[topic].log(data)

        except Exception as e:
            logger.error(f"Error handling unknown message for topic {topic}: {e}")

    def _handle_video_message(self, sample: Sample):
        try:
            topic = str(sample.key_expr)
            payload_bytes = bytes(sample.payload)
            data = json.loads(payload_bytes.decode('utf-8'))

            # Create video channel if it doesn't exist
            if topic not in self.video_channels:
                self.video_channels[topic] = CompressedVideoChannel(topic)
                logger.info(f"Created new video channel for topic {topic}")

            # Extract video data from the message
            if "data" not in data or "format" not in data:
                logger.warning(f"Invalid video message format for topic {topic}")
                return

            # Create CompressedImage message
            image_msg = CompressedVideo(
                timestamp=Timestamp(sec=int(data.get("timestamp", {}).get("sec", 0)),
                                  nsec=int(data.get("timestamp", {}).get("nsec", 0))),
                frame_id=data.get("frame_id", "camera"),
                data=bytes(data["data"]),
                format=data["format"]
            )

            # Send the video message
            self.video_channels[topic].log(image_msg)

        except Exception as e:
            logger.error(f"Error handling video message for topic {topic}: {e}")

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