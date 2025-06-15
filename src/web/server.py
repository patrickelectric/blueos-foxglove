import asyncio
import json
import logging
import os
from aiohttp import web
import socket

# Configure logging
logger = logging.getLogger("foxglove_bridge")

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
    return runner