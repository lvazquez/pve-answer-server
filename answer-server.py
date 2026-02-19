import logging
import json
import pathlib
import yaml
from typing import Optional

try:
    import tomlkit
    from aiohttp import web
    from jinja2 import Environment, FileSystemLoader, StrictUndefined, TemplateSyntaxError, UndefinedError
except ImportError as e:
    import sys
    message = """Could not import required packages.                                                                                                      
Please ensure you've installed all necessary packages (jinja2, PyYAML, tomlkit, aiohttp)! """
    print(message, file=sys.stderr)
    raise e

# Configuration Paths
CONFIG_DIR = pathlib.Path("./config")
DEFAULT_CONFIG_PATH = CONFIG_DIR / "defaults.yml"
TEMPLATE_FILE_PATH = pathlib.Path("./template/answer.toml.j2")

routes = web.RouteTableDef()

# Setup Jinja2 Environment
# StrictUndefined ensures an error is raised if a template variable is missing
jinja_env = Environment(
    loader=FileSystemLoader(str(TEMPLATE_FILE_PATH.parent)),
    undefined=StrictUndefined 
)

@routes.post("/answer")
async def answer(request: web.Request):
    try:
        request_data = json.loads(await request.text())
    except json.JSONDecodeError as e:
        return web.Response(
            status=400,
            text=f"Bad Request: failed to parse request contents: {e}",
        )    
    logging.info(f"Request from '{request.remote}' with MACs: {[nic.get('mac') for nic in request_data.get('network_interfaces', [])]}")

    try:
        answer_toml = create_answer(request_data)
        return web.Response(text=answer_toml, content_type='application/toml')
    except (ValueError, KeyError) as e:
        logging.error(f"Validation error: {e}")
        return web.Response(status=400, text=f"Config Validation Error: {e}")
    except (UndefinedError, TemplateSyntaxError) as e:
        logging.error(f"Template error: {e}")
        return web.Response(status=500, text=f"Template Error: {e}")
    except Exception as e:
        logging.exception(f"Unexpected error: {e}")
        return web.Response(status=500, text=f"Internal Server Error: {e}")

def load_yaml(path: pathlib.Path) -> dict:
    with open(path, 'r') as f:
        # safe_load returns None for empty files, so we return {} as a fallback
        return yaml.safe_load(f) or {}

def create_answer(request_data: dict) -> str:
    # 1. Load Default Configuration (always used as base)
    final_config = load_yaml(DEFAULT_CONFIG_PATH)
    logging.info(f"Default configuration values loaded.")

    # 2. Search for MAC-specific config and STOP at the first match
    mac_config = None

    for nic in request_data.get("network_interfaces", []):
        mac = nic.get("mac")
        if not mac:
            continue        
        mac_config = lookup_config_for_mac(mac)
        if mac_config is not None:
            logging.info(f"Match found for MAC: {mac}. Applying specific configuration.")
            # Stop searching once the first matching configuration is found
            break 

    # 3. If MAC-specific config is found, merge it over defaults
    if mac_config is not None:
        final_config.update(mac_config)
    else:
        logging.info("No MAC-specific config found. Using default values only.")

    # 4. Check for mandatory parameters
    required_fields = ['server_hostname', 'server_address']
    for field in required_fields:
        if field not in final_config:
            raise KeyError(f"Missing mandatory configuration field: '{field}'")

    # 5. Render Template using the filename part of our Path variable
    try:
        template = jinja_env.get_template(TEMPLATE_FILE_PATH.name)
        rendered_content = template.render(final_config)
    except UndefinedError as e:
        raise UndefinedError(f"A variable in the template was not found in YAML configs: {e}")

    # 6. Verify valid TOML output
    try:
        tomlkit.parse(rendered_content)
    except Exception as e:
        raise ValueError(f"Template rendered successfully but produced invalid TOML: {e}")

    return rendered_content

def lookup_config_for_mac(mac: str) -> Optional[dict]:
    mac = mac.lower()
    # Looking for config/mac_address.yml
    for filename in CONFIG_DIR.glob("*.yml"):
        if filename.name.lower().startswith(mac):
            return load_yaml(filename)
    return None

def assert_required_paths():
    if not CONFIG_DIR.exists():
        raise RuntimeError(f"Config directory '{CONFIG_DIR}' missing")
    if not DEFAULT_CONFIG_PATH.exists():
        raise RuntimeError(f"Default config file '{DEFAULT_CONFIG_PATH}' missing")
    if not TEMPLATE_FILE_PATH.exists():
        raise RuntimeError(f"Template file '{TEMPLATE_FILE_PATH}' missing")


if __name__ == "__main__":
    assert_required_paths()
    
    app = web.Application()
    logging.basicConfig(level=logging.INFO)
    app.add_routes(routes)
    
    print(f"Starting Jinja2-TOML Answer Server on port 8000...")
    web.run_app(app, host="0.0.0.0", port=8000)
