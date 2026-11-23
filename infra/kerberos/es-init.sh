#!/bin/sh
# Papeis do Elasticsearch e mapeamento dos principals Kerberos -> papeis.
# api@ENADE.LOCAL so le; consumidor@ENADE.LOCAL escreve no indice.
# manage_own_api_key: cada principal autenticado por Kerberos cria a propria API key (mesmos papeis).
set -eu
ES=http://elasticsearch:9200
AUTH="elastic:${ELASTIC_PASSWORD:?defina ELASTIC_PASSWORD}"
until curl -sf -u "$AUTH" "$ES/_cluster/health" >/dev/null; do echo "aguardando ES..."; sleep 3; done
put(){ curl -sf -u "$AUTH" -X PUT "$ES/$1" -H 'Content-Type: application/json' -d "$2" >/dev/null && echo "ok $1"; }
put _security/role/enade_leitura '{"cluster":["monitor","manage_own_api_key"],"indices":[{"names":["enade-*"],"privileges":["read","view_index_metadata"]}]}'
put _security/role/enade_escrita '{"cluster":["monitor","manage_own_api_key"],"indices":[{"names":["enade-*"],"privileges":["all"]}]}'
put _security/role_mapping/kerberos_api '{"enabled":true,"roles":["enade_leitura"],"rules":{"all":[{"field":{"realm.name":"kerb1"}},{"field":{"username":"api@ENADE.LOCAL"}}]}}'
put _security/role_mapping/kerberos_pipeline '{"enabled":true,"roles":["enade_escrita"],"rules":{"all":[{"field":{"realm.name":"kerb1"}},{"field":{"username":["consumidor@ENADE.LOCAL","produtor@ENADE.LOCAL"]}}]}}'
