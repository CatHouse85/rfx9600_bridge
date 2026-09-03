FROM python:3.11-alpine

RUN apk add --no-cache bash

WORKDIR /app

COPY rfx9600_bridge/rfx9600_listener.py /app/
COPY rfx9600_bridge/mqtt_bridge.py /app/
COPY rfx9600_bridge/run.sh /app/

RUN chmod +x /app/run.sh

CMD ["/app/run.sh"]
