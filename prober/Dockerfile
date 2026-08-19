FROM golang:1.26-bookworm AS build

ARG PB_VERSION=v0.9.0
ARG PB_GIT_SHA=unknown

WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY . ./
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-X main.Version=${PB_VERSION} -X main.GitSHA=${PB_GIT_SHA}" -o /out/prober ./cmd/prober

FROM alpine:3.23

ARG PB_VERSION=v0.9.0
ARG PB_GIT_SHA=unknown
ARG PB_BUILD_DATE=unknown

LABEL org.opencontainers.image.version="${PB_VERSION}" \
      org.opencontainers.image.revision="${PB_GIT_SHA}" \
      org.opencontainers.image.created="${PB_BUILD_DATE}" \
      org.opencontainers.image.title="PowerBlockade prober" \
      org.opencontainers.image.description="Synthetic warm-path latency prober for PowerBlockade"

RUN apk add --no-cache ca-certificates

RUN addgroup -g 65532 -S nonroot && \
    adduser -u 65532 -S -G nonroot -h /home/nonroot nonroot

# The frozen control corpus is bind-mounted read-only at this path by compose.
RUN mkdir -p /usr/local/share/powerblockade/corpus && \
    chown nonroot:nonroot /usr/local/share/powerblockade/corpus

WORKDIR /
COPY --from=build /out/prober /prober

USER nonroot:nonroot

ENTRYPOINT ["/prober"]
