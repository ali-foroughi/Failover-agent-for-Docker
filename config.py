# config.py
from dataclasses import dataclass
from typing import List

@dataclass
class ServerConfig:
    name: str
    containers: List[str]
    endpoint: str
    port: int

@dataclass
class GeneralConfig:
    heartbeat_interval: int
    check_heartbeat_interval: int
    heartbeat_timeout: int
    startup_grace_period: int
    restart_grace_period: int



GENERAL_CONFIG = GeneralConfig(
    heartbeat_interval=5,
    check_heartbeat_interval=5,
    heartbeat_timeout=20,
    startup_grace_period=20,    # grace period for initial startup
    restart_grace_period=30     # grace period for container restarts (in seconds)
)

# Server 1 Configuration File
SERVER1_CONFIG = ServerConfig(
    name="server1",
    containers=[
        "container-1",
        "container-2"
    ],
    endpoint="http://172.17.92.9:8000",  # URL of server 2
    port=8000
)

# Server 2 Configuration File
SERVER2_CONFIG = ServerConfig(
    name="server2",
    containers=[
        "container-1",
        "container-2"
    ],
    endpoint="http://172.17.92.20:8000",  # URL of server 1
    port=8000
)
