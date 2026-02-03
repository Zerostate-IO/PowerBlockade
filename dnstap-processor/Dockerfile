FROM golang:1.23-bookworm AS build

ARG PB_VERSION=0.4.0
ARG PB_GIT_SHA=unknown

WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY . ./
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-X main.Version=${PB_VERSION} -X main.GitSHA=${PB_GIT_SHA}" -o /out/dnstap-processor ./cmd/dnstap-processor

FROM alpine:3.20

ARG PB_VERSION=0.4.0
ARG PB_GIT_SHA=unknown
ARG PB_BUILD_DATE=unknown

LABEL org.opencontainers.image.version="${PB_VERSION}" \
      org.opencontainers.image.revision="${PB_GIT_SHA}" \
      org.opencontainers.image.created="${PB_BUILD_DATE}" \
      org.opencontainers.image.title="PowerBlockade dnstap-processor" \
      org.opencontainers.image.description="DNS event processor for PowerBlockade"

RUN apk add --no-cache ca-certificates

RUN addgroup -g 65532 -S nonroot && \
    adduser -u 65532 -S -G nonroot -h /home/nonroot nonroot

RUN mkdir -p /var/lib/dnstap-processor && \
    chown nonroot:nonroot /var/lib/dnstap-processor

WORKDIR /
COPY --from=build /out/dnstap-processor /dnstap-processor

USER nonroot:nonroot

ENTRYPOINT ["/dnstap-processor"]
