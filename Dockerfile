FROM python:3.14

RUN apt update && apt install -y alsa-utils pipewire-audio-client-libraries ffmpeg

WORKDIR /code
COPY ./requirements.txt /code/requirements.txt
RUN pip install --no-cache-dir --upgrade -r /code/requirements.txt
COPY ./app /code/app
ENV PYTHONUNBUFFERED=1
CMD ["fastapi", "run", "app/main.py", "--port", "80"]
