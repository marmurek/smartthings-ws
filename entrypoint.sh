#!/bin/bash

set -e

# Every setting lives in the YAML configuration file and can be overridden by an
# environment variable, which the application reads directly.
exec python3 main.py --config "${CONFIG_FILE:-config.yaml}"
