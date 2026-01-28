FROM golang:1.23-bookworm AS build

WORKDIR /src

COPY go.mod go.sum ./
RUN go mod download

COPY . ./
RUN CGO_ENABLED=0 GOOS=linux go build -o /out/dnstap-processor ./cmd/dnstap-processor

FROM gcr.io/distroless/static-debian12

WORKDIR /
COPY --from=build /out/dnstap-processor /dnstap-processor

USER nonroot:nonroot

ENTRYPOINT ["/dnstap-processor"]
