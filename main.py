"""Entry point for the SmartThings Local API."""

import uvicorn

from smartthings_ws.api import create_app
from smartthings_ws.config import configure_logging, load_settings, parse_args

cli_args = parse_args()
settings = load_settings(cli_args.config)
configure_logging(settings)

app = create_app(settings)

if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.dev_mode,
        log_level="debug" if settings.verbose else "info",
        access_log=settings.verbose,
    )
