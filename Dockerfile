FROM python:3.12-slim
WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY support support
COPY data data
CMD ["uvicorn", "support.main:app", "--host", "0.0.0.0", "--port", "8000"]
