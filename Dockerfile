
FROM python:3.12-slim

WORKDIR /project

ENV PYTHONPATH=/project

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt 

COPY . .

CMD ["streamlit", "run", "streamlit_app.py", "--server.address=0.0.0.0"]
