FROM powerdns/pdns-recursor-53:latest

USER 0:0

RUN apt-get update -qq && \
    apt-get install -y -qq --no-install-recommends inotify-tools && \
    rm -rf /var/lib/apt/lists/*

COPY --chmod=755 reloader.sh /usr/local/bin/reloader

ENTRYPOINT ["/usr/local/bin/reloader"]
