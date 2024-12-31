# Failover agent for Docker

This project is designed to handle failover for docker containers. It's designed in a active/passive mode. If any containers on "**primary**" server are down for more than the specified time, the failover will be triggered and "**backup**" server will become the active node. Once in active mode, the new agent will start the containers on the second server

Additionally, if the "**backup**" server doesn't receive heartbeat packets from the "**primary**" for more than the specified time, it will trigger the failover and become the active node. 


### Features

- Checking on the status of the containers (running or stopped)
- Grace period for restarting containers
- Heartbeat between the two nodes using HTTP POST requests


### Usage

#### Docker

- Copy the sample docker compose file to both hosts
- Edit the docker compose file
    - For the "**primary**" server, the value of `server1` should be passed in the command:

    ```
    command: ["python3", "main.py", "--server", "server1"]
    ```
    - For the "**backup**" server, the value of `server2` shoyld be passed in the command: 
    ```
    command: ["python3", "main.py", "--server", "server2"]
    ```
- Edit the `config.py` as needed and mount it at `/app/config.py` inside the container. Make sure the endpoints in the file are correctly configure to point to the other instance of the failover agent. 

- The docker network configuration should be in a way that both **primary** and **backup** nodes can access each other. 



#### Systemd

- Clone this repository on each server
- Create a virtual environment
```
python3 -m venv env
```

- Change source:
```
source env/bin/activate
```

- Install the pip packages
```
pip install -r requirements.txt
```
- Modify the `config.py` file to specify container names and API endpoints

- On the "**primary**" node run this command:
```
python3 main.py --server server1
```

- On the "**backup**" node run this command:
```
python3 main.py --server server2
```

#### Service configuration

If you want to deploy it using a systemd service, follow these steps:

- Create the systemd file: 
```
cat > /etc/systemd/system/failover-agent.service <<EOF
[Unit]
Description=failover agent
After=network.target

[Service]
Type=simple
WorkingDirectory=/opt/failover-agent
ExecStart=/opt/failover-agent/env/bin/python3 main.py --server server1
Restart=always
User=root

[Install]
WantedBy=multi-user.target
EOF
```

- Make sure to change `server1` to `server2` if creating the service on the "backup" node.
- Run the systemd commands to load and start the service
```
systemctl daemon-reload
```
```
systemctl enable failover-agent.service
```
```
systemctl start failover-agent.service
```


### General configuration

All the configuration can be changed by modifying `config.py`

- `heartbeat_interval`: seconds between each heartbeat
- `check_heartbeat_interval`: seconds between checking if a heartbeat has been received or not.

- `heartbeat_timeout`: seconds after which heartbeat is considered stopped and failover will be triggered 

- `startup_grace_period`: seconds before which container starts/stops are ignored
- `restart_grace_period`: seconds before which containers are allowed to be restated before failover is triggered

- `containers`: is a list of all containers that need to be stopped/started once a failover is triggered.

- `endpoint`: should point to the **other** instance of the agent 

- `port`: is the API port on which the agent will listen on.