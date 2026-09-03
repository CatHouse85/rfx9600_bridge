FROM python:3.11-alpine

RUN apk add --no-cache bash

WORKDIR /app

COPY rfx9600_listener.py mqtt_bridge.py run.sh /app/
RUN chmod +x /app/run.sh

RUN pip install paho-mqtt

CMD ["/app/run.sh"]
