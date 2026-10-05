FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir .
COPY app.py ./
COPY static ./static
COPY artifacts ./artifacts
COPY models ./models
COPY data/examples ./data/examples
EXPOSE 5051
CMD ["python", "app.py", "--host", "0.0.0.0", "--port", "5051"]
