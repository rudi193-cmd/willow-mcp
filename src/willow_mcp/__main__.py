"""Entry point: python3 -m willow_mcp [--serve] [--port PORT] [--host HOST]"""
from .server import main

# Observability (opt-in, egress-gated): inert unless WILLOW_SENTRY_DSN is set.
# Treats Sentry as a hostile egress destination — see observability.py. Wired
# here rather than in server.main() so it covers every MCP-client-spawned
# server (the lane the experiment observes); CLI subcommand one-shots via the
# console scripts deliberately do not init telemetry.
from .observability import init_observability

init_observability()
main()
