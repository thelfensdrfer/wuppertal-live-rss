FROM python:3.11

WORKDIR /app

# Set german locale to parse dates
RUN apt-get update && \
    apt-get install -y locales && \
    sed -i -e 's/# de_DE.UTF-8 UTF-8/de_DE.UTF-8 UTF-8/' /etc/locale.gen && \
    dpkg-reconfigure --frontend=noninteractive locales

ENV LANG de_DE.UTF-8
ENV LC_ALL de_DE.UTF-8

COPY poetry.lock pyproject.toml ./

RUN pip install poetry && \
	poetry config virtualenvs.create false && \
	poetry install --no-dev --no-interaction --no-ansi

COPY . .

# Start fastapi server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
