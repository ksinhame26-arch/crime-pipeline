FROM python:3.12-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY *.py .

# Registers the deployment in Prefect Cloud and runs the flow on schedule
CMD ["python", "etl_pipeline.py"]
