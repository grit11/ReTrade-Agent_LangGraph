FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 LANGGRAPH_STRICT_MSGPACK=true
WORKDIR /app
COPY . .
ARG INSTALL_EXTRAS=""
RUN if [ -n "$INSTALL_EXTRAS" ]; then pip install --no-cache-dir -e ".[${INSTALL_EXTRAS}]"; else pip install --no-cache-dir -e .; fi
RUN useradd -m -u 10001 retrade && mkdir -p runtime && chown -R retrade:retrade /app
USER retrade
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health',timeout=3)"
CMD ["python","scripts/run.py","--host","0.0.0.0"]
