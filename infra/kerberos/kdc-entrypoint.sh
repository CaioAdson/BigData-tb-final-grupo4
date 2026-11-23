#!/usr/bin/env bash
# Cria o banco do KDC, os principals de cada componente e exporta os keytabs para /keytabs
# (bind mount em ./secrets/keytabs, ignorado pelo Git). Nenhuma senha de servico existe:
# todos os principals usam chave aleatoria (-randkey) e se autenticam por keytab.
set -euo pipefail
REALM=ENADE.LOCAL
: "${KRB5_MASTER_PASSWORD:?defina KRB5_MASTER_PASSWORD no .env}"

if [ ! -f /var/lib/krb5kdc/principal ]; then
  kdb5_util create -s -r "$REALM" -P "$KRB5_MASTER_PASSWORD"
fi

# principal                     keytab
PRINCIPAIS="kafka/kafka:kafka HTTP/elasticsearch:HTTP kafka-admin:kafka-admin api:api consumidor:consumidor produtor:produtor"
mkdir -p /keytabs
for item in $PRINCIPAIS; do
  p="${item%%:*}"; arq="/keytabs/${item##*:}.keytab"
  kadmin.local -q "getprinc $p@$REALM" 2>/dev/null | grep -q "Principal: $p@$REALM" \
    || kadmin.local -q "addprinc -randkey $p@$REALM" >/dev/null
  # -norandkey: reexportar nao invalida keytabs ja distribuidos
  rm -f "$arq"; kadmin.local -q "ktadd -norandkey -k $arq $p@$REALM" >/dev/null
  chmod 644 "$arq"   # laboratorio: containers rodam com UIDs diferentes
  echo "keytab: $arq ($p@$REALM)"
done
touch /keytabs/.pronto
exec krb5kdc -n
