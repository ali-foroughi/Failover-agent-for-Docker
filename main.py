from fastapi import FastAPI, HTTPException
import uvicorn
import argparse
import threading
import time
import requests
from typing import Dict
from monitor import ContainerMonitor, ServerConfig, ServerRole
from config import SERVER1_CONFIG, SERVER2_CONFIG, GENERAL_CONFIG

server_configs = GENERAL_CONFIG

class HeartbeatMonitor:
    def __init__(self, monitor, config):
        self.monitor = monitor
        self.config = config
        self.last_heartbeat = 0
        self.heartbeat_interval = server_configs.heartbeat_interval  # seconds
        self.check_heartbeat_interval = server_configs.check_heartbeat_interval # seconds
        self.heartbeat_timeout = server_configs.heartbeat_timeout   # seconds
        self._stop_event = threading.Event()
        self._failover_lock = threading.Lock()  # Add lock for failover process
        
    def initiate_failover(self):
        """
        Centralized method to handle failover process.
        Returns True if failover was successful.
        """
        with self._failover_lock:  # Ensure only one failover happens at a time
            if self.monitor.role == ServerRole.BACKUP:
                self.monitor.logger.info("Initiating failover process...")
                if self.monitor.become_primary(self.config.containers):
                    self.monitor.logger.info("Successfully took over as primary")
                    return True
                else:
                    self.monitor.logger.error("Failed to take over as primary")
            return False

    def send_heartbeat(self):
        """Send heartbeat if we're the primary server"""
        while not self._stop_event.is_set():
            if self.monitor.role == ServerRole.PRIMARY:
                try:
                    requests.post(
                        f"{self.monitor.other_server_url}/heartbeat",
                        json={"server": self.monitor.server_name}
                    )
                    self.monitor.logger.debug(f"Heartbeat sent to backup server")
                except Exception as e:
                    self.monitor.logger.error(f"Failed to send heartbeat: {str(e)}")
            
            time.sleep(self.heartbeat_interval)
    
    def check_heartbeat(self):
        """Check heartbeat if we're the backup server"""
        while not self._stop_event.is_set():
            if self.monitor.role == ServerRole.BACKUP:
                current_time = time.time()
                if self.last_heartbeat > 0:  # Only check if we've received at least one heartbeat
                    time_since_last_heartbeat = current_time - self.last_heartbeat
                    if time_since_last_heartbeat > self.heartbeat_timeout:
                        self.monitor.logger.warning("No heartbeat received from primary for too long!")
                        self.initiate_failover()
            
            time.sleep(self.check_heartbeat_interval)
            
    def start(self):
        """Start both heartbeat threads"""
        self.sender_thread = threading.Thread(
            target=self.send_heartbeat,
            daemon=True
        )
        self.checker_thread = threading.Thread(
            target=self.check_heartbeat,
            daemon=True
        )
        self.sender_thread.start()
        self.checker_thread.start()
        
    def stop(self):
        """Stop the heartbeat threads"""
        self._stop_event.set()

def main():
    parser = argparse.ArgumentParser(description='Container Monitor')
    parser.add_argument('--server', 
                       type=str,
                       choices=['server1', 'server2'],
                       required=True,
                       help='Specify which server this is (server1 or server2)')
    
    args = parser.parse_args()
    
    # Select the appropriate configuration and initial role
    if args.server == 'server1':
        config = SERVER1_CONFIG
        initial_role = ServerRole.PRIMARY
    else:
        config = SERVER2_CONFIG
        initial_role = ServerRole.BACKUP
    
    # Initialize the monitor with shared failover lock
    monitor = ContainerMonitor(
        server_name=config.name,
        other_server_url=config.endpoint,
        initial_role=initial_role
    )
    
    # Initialize the heartbeat monitor
    heartbeat = HeartbeatMonitor(monitor, config)
    
    # Create FastAPI app
    app = FastAPI()
    
    @app.post("/become_primary")
    async def become_primary(request: Dict[str, str]):
        server_name = request.get("server")
        if not server_name:
            raise HTTPException(status_code=400, detail="Server name required")
        
        with heartbeat._failover_lock:
            if monitor.become_primary(config.containers):
                return {"message": "Successfully transitioned to primary role"}
            else:
                raise HTTPException(status_code=500, detail="Failed to transition to primary role")
    
    @app.post("/heartbeat")
    async def receive_heartbeat(request: Dict[str, str]):
        server_name = request.get("server")
        if not server_name:
            raise HTTPException(status_code=400, detail="Server name required")
        
        heartbeat.last_heartbeat = time.time()
        monitor.logger.debug(f"Heartbeat received from {server_name}")
        return {"message": "Heartbeat received"}
    
    # Modified monitor_containers_wrapper to use the failover lock
    def monitor_containers_wrapper():
        """Wrapper function to handle container monitoring with proper locking"""
        while True:
            if monitor.role == ServerRole.PRIMARY:
                for container_name in config.containers:
                    if not monitor.should_check_container(container_name):
                        continue
                        
                    if not monitor.get_container_status(container_name):
                        monitor.logger.warning(f"Container {container_name} appears to be down, verifying...")
                        
                        if not monitor.verify_container_health(container_name):
                            monitor.logger.warning(f"Container {container_name} confirmed down!")
                            
                            with heartbeat._failover_lock:
                                if monitor.stop_all_containers(config.containers):
                                    monitor.logger.info("All containers stopped successfully")
                                    
                                    if monitor.notify_other_server():
                                        monitor.logger.info("Other server notified successfully")
                                        monitor.become_backup(config.containers)
                                    else:
                                        monitor.logger.error("Failed to notify other server")
                                else:
                                    monitor.logger.error("Failed to stop all containers")
            
            time.sleep(10)
    
    # Start monitoring in a separate thread with the wrapper
    monitoring_thread = threading.Thread(
        target=monitor_containers_wrapper,
        daemon=True
    )
    monitoring_thread.start()
    
    # Start the heartbeat monitoring
    heartbeat.start()
    
    # Start the API server
    try:
        uvicorn.run(app, host="0.0.0.0", port=config.port)
    finally:
        heartbeat.stop()

if __name__ == "__main__":
    main()
