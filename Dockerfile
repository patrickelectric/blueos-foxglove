FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

# Set working directory
WORKDIR /app

# Copy project files
COPY pyproject.toml .
COPY src/ src/

# Install dependencies using uv
RUN uv venv
RUN uv pip install .

LABEL version="0.0.0"
LABEL permissions='{\
  "NetworkMode": "host",\
  "HostConfig": {\
    "Privileged": true,\
    "NetworkMode": "host"\
  }\
}'
LABEL authors='[\
  {\
    "name": "Patrick José Pereira",\
    "email": "patrickelectric@gmail.com"\
  }\
]'
LABEL company='{\
  "about": "",\
  "name": "Patrick José Pereira",\
  "email": "patrickelectric@gmail.com"\
}'
LABEL readme="https://raw.githubusercontent.com/patrickelectric/blueos-foxglove/master/README.md"
LABEL type="other"
LABEL tags='[\
  "zenoh",\
  "foxglove",\
  "mavlink"\
]'

# Run the application
CMD ["uv", "run", "src/main.py"]