FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent.py .
# mount your actual DNS log into /logs/query.log
CMD ["python", "agent.py", "--file", "/logs/query.log"]
