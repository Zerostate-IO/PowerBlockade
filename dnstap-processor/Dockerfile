FROM golang:1.23-bookworm AS build

WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY . ./
RUN CGO_ENABLED=0 GOOS=linux go build -o /out/dnstap-processor ./cmd/dnstap-processor

FROM alpine:3.20

# Install ca-certificates for HTTPS calls
RUN apk add --no-cache ca-certificates

# Create non-root user
RUN addgroup -g 65532 -S nonroot && \
    adduser -u 65532 -S -G nonroot -h /home/nonroot nonroot

# Create buffer directory with correct ownership
RUN mkdir -p /var/lib/dnstap-processor && \
    chown nonroot:nonroot /var/lib/dnstap-processor

WORKDIR /
COPY --from=build /out/dnstap-processor /dnstap-processor

USER nonroot:nonroot

ENTRYPOINT ["/dnstap-processor"]
