FROM python:3.11-slim

RUN pip install paho-mqtt

WORKDIR /app
COPY listener.py /app/listener.py
COPY run.sh /app/run.sh

RUN chmod +x /app/run.sh

CMD ["/app/run.sh"]