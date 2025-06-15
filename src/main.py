import asyncio
import logging
from web.server import start_web_server
from fox.bridge import Bridge

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("foxglove_bridge")

async def main():
    # Start web server
    web_runner = await start_web_server()

    # Start bridge
    bridge = Bridge()
    await bridge.start()

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    finally:
        bridge.cleanup()
        await web_runner.cleanup()

if __name__ == "__main__":
    asyncio.run(main())
