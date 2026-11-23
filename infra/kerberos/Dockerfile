# KDC MIT Kerberos do laboratorio (realm ENADE.LOCAL).
FROM debian:bookworm-slim
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      krb5-kdc krb5-admin-server krb5-user && rm -rf /var/lib/apt/lists/*
COPY krb5.conf /etc/krb5.conf
COPY kdc-entrypoint.sh /usr/local/bin/kdc-entrypoint.sh
RUN chmod +x /usr/local/bin/kdc-entrypoint.sh
EXPOSE 88/tcp 88/udp
ENTRYPOINT ["/usr/local/bin/kdc-entrypoint.sh"]
