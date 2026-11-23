FROM python:3.12-slim

# Kerberos:
#  - Kafka (SASL/GSSAPI): o wheel do confluent-kafka vem SEM GSSAPI ("Current build options: PLAIN
#    SASL_SCRAM OAUTHBEARER"), entao compilamos o librdkafka com libsasl2 (Cyrus SASL + plugin GSSAPI MIT)
#    e o confluent-kafka contra ele.
#  - Elasticsearch (SPNEGO): pacote python 'gssapi'.
ARG LIBRDKAFKA_VERSION=2.6.1
ARG CONFLUENT_KAFKA_VERSION=2.6.1
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      libkrb5-3 libgssapi-krb5-2 krb5-user libsasl2-2 libsasl2-modules-gssapi-mit libssl3t64 zlib1g libzstd1 liblz4-1 \
      build-essential curl ca-certificates libsasl2-dev libssl-dev zlib1g-dev libzstd-dev liblz4-dev libkrb5-dev \
    && curl -fsSL https://github.com/confluentinc/librdkafka/archive/refs/tags/v${LIBRDKAFKA_VERSION}.tar.gz | tar -xz -C /tmp \
    && cd /tmp/librdkafka-${LIBRDKAFKA_VERSION} \
    && ./configure --prefix=/usr/local --enable-sasl --enable-ssl --enable-zstd --enable-lz4-ext --disable-curl \
    && make -j"$(nproc)" && make install && ldconfig \
    && pip install --no-cache-dir --no-binary confluent-kafka "confluent-kafka==${CONFLUENT_KAFKA_VERSION}" "gssapi>=1.8,<2" \
    && cd / && rm -rf /tmp/librdkafka-* \
    && apt-get purge -y build-essential curl libsasl2-dev libssl-dev zlib1g-dev libzstd-dev liblz4-dev libkrb5-dev \
    && apt-get autoremove -y && rm -rf /var/lib/apt/lists/* \
    && python -c "import confluent_kafka as c; c.Producer({'security.protocol':'SASL_PLAINTEXT','sasl.mechanisms':'GSSAPI','sasl.kerberos.keytab':'/dev/null','sasl.kerberos.principal':'teste'}); print('GSSAPI ok', c.libversion())"
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY enade ./enade
COPY mapping ./mapping
ENV PYTHONUNBUFFERED=1
CMD ["python", "-m", "enade.consumidor"]
