FROM reg.zcore.local/proxy_cache/docker:27.4.0-rc.4-dind
RUN apk add --no-cache python3 curl python3-pip iputils-ping nano py3-pip iproute2 inetutils-traceroute \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
RUN pip  install --break-system-packages --index-url http://172.20.14.54:5000/index/ --trusted-host 172.20.14.54 -r requirements.txt
CMD ["python3", "main.py"]
