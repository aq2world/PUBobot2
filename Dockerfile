FROM python:3.9

# Generate user, create working directory
RUN useradd --create-home --shell /bin/bash pubobot -u 1000
RUN mkdir -p /opt/pubobot
COPY . /opt/pubobot
WORKDIR /opt/pubobot

# Install python libraries
RUN pip install -r requirements.txt

# Change ownership to the pubobot user, run process
RUN chown -R pubobot:pubobot /opt/pubobot
USER pubobot
CMD ["python3.9", "PUBobot2.py"]