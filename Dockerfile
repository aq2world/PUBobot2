FROM python:3.9-alpine
ARG DEBIAN_FRONTEND=noninteractive

RUN apk add ttf-dejavu
RUN adduser -D -s /bin/bash -u 1001 pubobot
USER pubobot
COPY PUBobot2.py requirements.txt /home/pubobot/
COPY config.example.cfg /home/pubobot/config.cfg
RUN mkdir -p /home/pubobot/locales/compiled
WORKDIR /home/pubobot/
RUN pip install -r requirements.txt

# Copy files over
COPY . /home/pubobot/
CMD ["python3", "PUBobot2.py"]
