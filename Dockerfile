FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    ANVIL_API_KEY=change-me
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY tests ./tests
RUN python -m pip install --no-cache-dir -e . && python -m unittest discover -s tests
EXPOSE 8787
CMD ["anvil-compile", "serve", "--host", "0.0.0.0", "--port", "8787"]
