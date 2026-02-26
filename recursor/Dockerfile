FROM powerdns/pdns-recursor-53:latest

USER 0:0

COPY --chmod=755 docker-entrypoint.sh /docker-entrypoint.sh
COPY --chmod=755 migrate-settings.sh /usr/local/bin/migrate-recursor-settings

ENTRYPOINT ["/docker-entrypoint.sh"]

# Keep the upstream default binary invocation, but non-daemonized.
CMD ["pdns_recursor", "--daemon=no", "--config-dir=/etc/pdns-recursor", "--enable-old-settings"]
