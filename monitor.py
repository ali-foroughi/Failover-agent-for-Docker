import docker
import requests
import time
import logging
from typing import List, Dict
from dataclasses import dataclass
from enum import Enum
from collections import defaultdict
from config import GENERAL_CONFIG

server_configs = GENERAL_CONFIG

class ServerRole(Enum):
    PRIMARY = "primary"
    BACKUP = "backup"

@dataclass
class ServerConfig:
    name: str
    containers: List[str]
    endpoint: str
    port: int

class ContainerMonitor:
    def __init__(self, server_name: str, other_server_url: str, initial_role: ServerRole):
        self.server_name = server_name
        self.other_server_url = other_server_url
        self.role = initial_role
        self.docker_client = docker.from_env()
        self.logger = self._setup_logger()
        self.startup_grace_period = server_configs.startup_grace_period  # grace period for initial startup
        self.restart_grace_period = server_configs.restart_grace_period  # grace period for container restarts (in seconds)
        self.container_start_time = 0
        self.container_down_times = defaultdict(float)  # Tracks when containers first went down
        
    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger(f'container_monitor_{self.server_name}')
        logger.setLevel(logging.INFO)
        handler = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        handler.setFormatter(formatter)
        logger.addHandler(handler)
        return logger

    def should_check_container(self, container_name: str) -> bool:
        """
        Determines if we should check a container's health based on grace period
        and other conditions.
        """
        # Skip checks during initial startup grace period
        time_since_start = time.time() - self.container_start_time
        if time_since_start < self.startup_grace_period:
            self.logger.debug(f"In startup grace period for {container_name}, {int(self.startup_grace_period - time_since_start)}s remaining")
            return False
            
        try:
            # Make sure container exists before checking
            self.docker_client.containers.get(container_name)
            return True
        except docker.errors.NotFound:
            self.logger.error(f"Container {container_name} not found")
            return False
        except Exception as e:
            self.logger.error(f"Error accessing container {container_name}: {str(e)}")
            return False



    def get_container_status(self, container_name: str) -> bool:
        try:
            container = self.docker_client.containers.get(container_name)
            is_running = container.status == 'running'
            
            # If container is running, reset its down time
            if is_running:
                if container_name in self.container_down_times:
                    self.logger.info(f"Container {container_name} is back up")
                    del self.container_down_times[container_name]
            else:
                # If container just went down, record the time
                if container_name not in self.container_down_times:
                    self.logger.warning(f"Container {container_name} appears to be down, starting grace period")
                    self.container_down_times[container_name] = time.time()
                    
            return is_running
        except docker.errors.NotFound:
            self.logger.error(f"Container {container_name} not found")
            return False
        except Exception as e:
            self.logger.error(f"Error checking container {container_name}: {str(e)}")
            return False

    def wait_for_containers_startup(self, containers: List[str], timeout: int = 300) -> bool:
        """
        Wait for all containers to be in running state with a timeout.
        Returns True if all containers are running, False if timeout is reached.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            all_running = True
            for container_name in containers:
                if not self.get_container_status(container_name):
                    all_running = False
                    break
            
            if all_running:
                self.logger.info("All containers are now running")
                return True
                
            self.logger.info("Waiting for containers to start...")
            time.sleep(10)
            
        self.logger.error(f"Timeout reached while waiting for containers to start")
        return False

    def stop_all_containers(self, containers: List[str]) -> bool:
        try:
            for container_name in containers:
                container = self.docker_client.containers.get(container_name)
                container.stop(timeout=0)  # Equivalent to docker stop -t 0
                self.logger.info(f"Stopped container: {container_name}")
            return True
        except Exception as e:
            self.logger.error(f"Error stopping containers: {str(e)}")
            return False

    def start_all_containers(self, containers: List[str]) -> bool:
        try:
            for container_name in containers:
                container = self.docker_client.containers.get(container_name)
                container.start()
                self.logger.info(f"Started container: {container_name}")
            
            self.container_start_time = time.time()
            # Wait for containers to actually start
            if self.wait_for_containers_startup(containers):
                return True
            return False
        except Exception as e:
            self.logger.error(f"Error starting containers: {str(e)}")
            return False

    def notify_other_server(self) -> bool:
        try:
            response = requests.post(
                f"{self.other_server_url}/become_primary",
                json={"server": self.server_name}
            )
            return response.status_code == 200
        except Exception as e:
            self.logger.error(f"Error notifying other server: {str(e)}")
            return False

    def become_backup(self, containers: List[str]):
        self.role = ServerRole.BACKUP
        self.logger.info(f"{self.server_name} transitioning to BACKUP role")
        if self.stop_all_containers(containers):
            self.logger.info("All containers stopped, now in backup mode")
        else:
            self.logger.error("Failed to stop all containers while transitioning to backup")

    def become_primary(self, containers: List[str]) -> bool:
        self.role = ServerRole.PRIMARY
        self.logger.info(f"{self.server_name} transitioning to PRIMARY role")
        return self.start_all_containers(containers)


    def verify_container_health(self, container_name: str) -> bool:
        """
        Verify container health with consecutive checks and respect restart grace period
        """
        # First check if the container is in restart grace period
        if container_name in self.container_down_times:
            time_since_down = time.time() - self.container_down_times[container_name]
            if time_since_down < self.restart_grace_period:
                self.logger.info(f"Container {container_name} is in restart grace period, {int(self.restart_grace_period - time_since_down)}s remaining")
                return True  # Consider container healthy during grace period
        
        # Perform multiple checks to verify container is actually down
        consecutive_checks = 3
        check_interval = 5  # seconds
        
        for i in range(consecutive_checks):
            if self.get_container_status(container_name):
                return True
            
            if i < consecutive_checks - 1:  # Don't sleep after last check
                time.sleep(check_interval)
        
        # If we get here, container has been down for more than grace period
        time_since_down = time.time() - self.container_down_times[container_name]
        if time_since_down >= self.restart_grace_period:
            self.logger.error(f"Container {container_name} has been down for {int(time_since_down)}s, exceeding grace period")
            return False
        
        return True

    def monitor_containers(self, containers: List[str]):
        self.logger.info(f"Starting monitor in {self.role.value} mode")
        
        # If primary, ensure containers are started and wait for initial startup
        if self.role == ServerRole.PRIMARY:
            if not self.start_all_containers(containers):
                self.logger.error("Failed to start containers initially")
                return
        
        while True:
            if self.role == ServerRole.PRIMARY:
                # Skip checks during grace period
                time_since_start = time.time() - self.container_start_time
                if time_since_start < self.startup_grace_period:
                    self.logger.info(f"In grace period, {int(self.startup_grace_period - time_since_start)}s remaining")
                    time.sleep(30)
                    continue

                for container_name in containers:
                    # Perform multiple checks to verify container is actually down
                    if not self.verify_container_health(container_name):
                        self.logger.warning(f"Container {container_name} failed health check!")
                        
                        # Stop all containers and transition to backup
                        if self.stop_all_containers(containers):
                            self.logger.info("All containers stopped successfully")
                            
                            # Notify other server to become primary
                            if self.notify_other_server():
                                self.logger.info("Other server notified successfully")
                                self.become_backup(containers)
                            else:
                                self.logger.error("Failed to notify other server")
                        else:
                            self.logger.error("Failed to stop all containers")
            
            time.sleep(50)
