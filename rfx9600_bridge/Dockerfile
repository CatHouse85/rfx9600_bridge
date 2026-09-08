FROM python:3.11-alpine

RUN apk add --no-cache bash

WORKDIR /app

COPY run.sh /app/
COPY mqtt_bridge.py /app/
COPY rfx9600_listener.py /app/

RUN python3 -m pip install paho-mqtt

RUN chmod +x /app/run.sh

CMD ["/app/run.sh"]
