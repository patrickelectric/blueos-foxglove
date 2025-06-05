import asyncio
import json
import logging
import os
from aiohttp import web
import foxglove
from foxglove import Channel
from foxglove.channels import LocationFixChannel, LogChannel
from foxglove.schemas import LocationFix, Log, LogLevel, Timestamp
from foxglove.websocket import Capability
import socket
import zenoh
from zenoh import Session, Sample

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("foxglove_bridge")

foxglove.set_log_level("DEBUG")

# Get the directory of the current script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Load extension configuration
with open(f"{SCRIPT_DIR}/html/extension.json", 'r') as f:
    EXTENSION_CONFIG = json.load(f)

# Load HTML template
with open(f"{SCRIPT_DIR}/html/index.html", 'r') as f:
    HTML_TEMPLATE = f.read()

def get_unused_port():
    """
    Finds and returns an unused TCP port number.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(('localhost', 0))  # Bind to an available port
    _, port = sock.getsockname()
    sock.close()
    return port

async def handle_web_request(request):
    """Handle web requests and serve the HTML page."""
    return web.Response(text=HTML_TEMPLATE, content_type='text/html')

async def handle_register_service(request):
    """Handle requests to /register_service and return the extension configuration."""
    return web.json_response(EXTENSION_CONFIG)

async def start_web_server():
    """Start the web server."""
    app = web.Application()
    app.router.add_get('/', handle_web_request)
    app.router.add_get('/register_service', handle_register_service)
    runner = web.AppRunner(app)
    await runner.setup()
    port = get_unused_port()
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"Web server started at http://0.0.0.0:{port}")

async def main():
    # Start web server
    await start_web_server()

    conf = zenoh.Config()
    conf.insert_json5("mode", '"peer"')
    session = zenoh.open(conf)

    location_fix_channel = LocationFixChannel("vehicle/position")
    mavlink_channels = {}

    # Start Foxglove server on 0.0.0.0
    server = foxglove.start_server(
        name="mavlink_server",
        capabilities=[Capability.ClientPublish],
        host="0.0.0.0",
        port=8765
    )
    logger.info("Foxglove server started at ws://0.0.0.0:8765")

    def mavlink_callback(sample: Sample):
        try:
            payload_bytes = bytes(sample.payload)
            try:
                data = json.loads(payload_bytes.decode('utf-8'))
            except json.JSONDecodeError:
                return

            if not isinstance(data, dict):
                return

            if not "message" in data:
                return

            msg = data["message"]

            if not "type" in msg:
                return

            msg_type = msg["type"]
            topic = f"mavlink/1/1/{msg_type}"

            if topic not in mavlink_channels:
                mavlink_channels[topic] = Channel(topic, message_encoding="json")

            # Send message
            mavlink_channels[topic].log(data)

            if msg_type == "GLOBAL_POSITION_INT":
                location_fix = LocationFix(
                    frame_id="map",
                    latitude=msg["lat"] / 1e7,  # Convert to degrees
                    longitude=msg["lon"] / 1e7,  # Convert to degrees
                    altitude=msg["alt"] / 1000.0,  # Convert to meters
                )
                location_fix_channel.log(location_fix)

        except Exception as e:
            logger.error(f"Error processing message: {e}")
            pass

    service_channels = {}
    def services_callback(sample: Sample):
        payload_bytes = bytes(sample.payload)
        try:
            data = json.loads(payload_bytes.decode('utf-8'))
        except json.JSONDecodeError:
            return

        if not isinstance(data, dict):
            return

        if not "message" in data:
            return

        topic = str(sample.key_expr)

        if topic not in service_channels:
            service_channels[topic] = LogChannel(topic)

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
        service_channels[topic].log(log_msg)


    session.declare_subscriber("mavlink/1/1/**", mavlink_callback)
    session.declare_subscriber("services/**/log", services_callback)

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        session.close()

if __name__ == "__main__":
    asyncio.run(main())
