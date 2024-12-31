FROM docker:27.4.0-rc.4-dind
RUN apk add --no-cache python3 curl python3-pip iputils-ping nano py3-pip iproute2 inetutils-traceroute \
    rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
RUN pip install -r requirements.txt
CMD ["python3", "main.py"]
