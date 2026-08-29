# Blueprint image for AgentDNS Sentinel.
#
# The base image provides Docker-in-Docker, so the whole Compose lab runs inside
# one Runloop Devbox. The repository is baked in at /workspace/agentdns-sentinel;
# `scripts/runloop_lab.py up` re-syncs the working tree on top of it, so you can
# iterate on the lab without rebuilding the blueprint.
FROM runloop:runloop/universal-ubuntu-24.04-x86_64-dnd

WORKDIR /workspace/agentdns-sentinel
COPY . .
