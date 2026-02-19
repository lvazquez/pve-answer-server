import logging
import json
import pathlib
import yaml
from typing import Optional
# Used for thread offloading
import asyncio

try:
    import tomlkit
    from aiohttp import web
    from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateSyntaxError, UndefinedError
except ImportError as e:
    import sys
    message = "Could not import required packages. Please install: jinja2, PyYAML, tomlkit, aiohttp"
    print(message, file=sys.stderr)
    raise e

# Configuration Paths
CONFIG_DIR = pathlib.Path("./config")
DEFAULT_CONFIG_PATH = CONFIG_DIR / "defaults.yml"
TEMPLATE_FILE_PATH = pathlib.Path("./template/answer.toml.j2")

routes = web.RouteTableDef()

# Setup Jinja2 Environment
jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_FILE_PATH.parent)),
    # ensures an error is raised if a template variable is missing
    undefined=StrictUndefined 
)

# Global variables to store cached content
cached_default_config = {}
cached_template = None

@routes.post("/answer")
async def answer(request: web.Request):
    try:
        request_data = json.loads(await request.text())
    except json.JSONDecodeError as e:
        return web.Response(status=400, text=f"Bad Request: {e}")
    logging.info(f"Request from '{request.remote}' with MACs: {[nic.get('mac') for nic in request_data.get('network_interfaces', [])]}")

    try:
        # We now await the answer creation
        answer_toml = await create_answer(request_data)
        return web.Response(text=answer_toml, content_type='application/toml')
    except (ValueError, KeyError) as e:
        logging.error(f"Validation error: {e}")
        return web.Response(status=400, text=f"Config Validation Error: {e}")
    except (UndefinedError, TemplateSyntaxError) as e:
        logging.error(f"Template error: {e}")
        return web.Response(status=500, text=f"Template Error: {e}")
    except Exception as e:
        logging.exception(f"Unexpected error: {e}")
        return web.Response(status=500, text=f"Internal Server Error")

def load_yaml_sync(path: pathlib.Path) -> dict:
    """Synchronous helper for reading YAML files."""
    with open(path, 'r') as f:
        return yaml.safe_load(f) or {}

def lookup_config_for_mac_sync(mac: str) -> Optional[dict]:
    """Synchronous helper for globbing and reading MAC config."""
    mac_lower = mac.lower()
    for filename in CONFIG_DIR.glob("*.yml"):
        if filename.name.lower().startswith(mac_lower):
            return load_yaml_sync(filename)
    return None

async def create_answer(request_data: dict) -> str:
    # Use the pre-loaded default config (Memory access is instant)
    final_config = cached_default_config.copy()

    # Search for MAC-specific config and STOP at the first match
    mac_config = None
    for nic in request_data.get("network_interfaces", []):
        mac = nic.get("mac")
        if not mac:
            continue
        
        # Run the blocking search/read in a separate thread
        mac_config = await asyncio.to_thread(lookup_config_for_mac_sync, mac)
        if mac_config is not None:
            break 

    # If MAC-specific config is found, merge it over defaults
    if mac_config is not None:
        logging.info(f"Match found for MAC: {mac}. Applying specific configuration.")
        final_config.update(mac_config)
    else:
        logging.info("No MAC-specific config found. Using default values only.")

    # Check for mandatory parameters
    for field in ['server_hostname', 'server_address']:
        if field not in final_config:
            raise KeyError(f"Mandatory field '{field}' missing")

    # Render Template (using cached template object)
    try:
        rendered_content = cached_template.render(final_config)
    except UndefinedError as e:
        raise UndefinedError(f"A variable in the template was missing in YAML configs: {e}")

    # Verify valid TOML output
    try:
        tomlkit.parse(rendered_content)
    except Exception as e:
        raise ValueError(f"Invalid TOML generated: {e}")

    return rendered_content

def startup_cache():
    """Load static files into memory before the server starts."""
    global cached_default_config, cached_template
    
    if not DEFAULT_CONFIG_PATH.exists() or not TEMPLATE_FILE_PATH.exists():
        raise RuntimeError("Required config or template files are missing!")

    cached_default_config = load_yaml_sync(DEFAULT_CONFIG_PATH)
    cached_template = jinja_env.get_template(TEMPLATE_FILE_PATH.name)
    logging.info("Templates and default configs cached in memory.")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Pre-load required config and template files
    startup_cache()
    
    app = web.Application()
    app.add_routes(routes)
    
    print(f"Starting Non-Blocking Answer Server on port 8000...")
    web.run_app(app, host="0.0.0.0", port=8000)
    
