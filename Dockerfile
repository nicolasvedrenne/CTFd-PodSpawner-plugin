FROM alpine:3.20

RUN apk add --no-cache ca-certificates

WORKDIR /src
COPY . /src/plugin/
RUN rm /src/plugin/Dockerfile

CMD ["sh", "-c", "ls -la /src/k8sspawn && echo 'Plugin image ready'"]
