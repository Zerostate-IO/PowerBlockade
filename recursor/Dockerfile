FROM powerdns/pdns-recursor-51:latest

USER 0:0

COPY --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh

ENTRYPOINT ["/docker-entrypoint.sh"]

# Keep the upstream default binary invocation, but non-daemonized.
CMD ["pdns_recursor", "--daemon=no", "--config-dir=/etc/pdns-recursor"]
