FROM python:3.6.4-alpine3.7

RUN apk add --no-cache --virtual .build-deps git

COPY requirements.txt /app/requirements.txt

RUN pip install --no-cache-dir -r /app/requirements.txt
RUN apk del .build-deps

COPY sandlibrarian.py /app/
WORKDIR /app/

CMD python sandlibrarian.py
