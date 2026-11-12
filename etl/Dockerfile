FROM python:3.12-slim
WORKDIR /etl
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . ./etl/
CMD ["python", "-m", "etl.load"]