FROM python:3.9
ARG DEBIAN_FRONTEND=noninteractive

RUN useradd -ms /bin/bash -u 1001 pubobot
USER pubobot
COPY PUBobot2.py requirements.txt /home/pubobot/
WORKDIR /home/pubobot/
RUN pip install -r requirements.txt

# Copy files over
COPY . /home/pubobot/
CMD ["python3", "PUBobot2.py"]