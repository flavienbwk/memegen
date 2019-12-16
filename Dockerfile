FROM python:3.6-alpine

RUN apk add --no-cache --virtual .build-deps git gcc make build-base bash jpeg-dev zlib-dev tiff-dev freetype-dev lcms2-dev tk-dev tcl-dev openjpeg-dev
COPY ./memegen /root/memegen

RUN pip install pipenv
WORKDIR /root/memegen

RUN pipenv install --system --deploy --ignore-pipfile

ENTRYPOINT ["python", "manage.py", "runserver", "--host", "0.0.0.0", "--port", "5000"]

EXPOSE 5000