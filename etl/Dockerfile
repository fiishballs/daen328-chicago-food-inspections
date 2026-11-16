
FROM python:3.12-slim

WORKDIR /project

ENV PYTHONPATH=/project

COPY etl/requirements.txt ./etl/requirements.txt

RUN pip install --no-cache-dir \
    -r etl/requirements.txt \
    pytest

COPY etl/ ./etl/
COPY tests/ ./tests/
COPY db/init/ ./db/init/

CMD ["python", "-m", "etl.load"]
