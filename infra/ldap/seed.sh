#!/usr/bin/env bash
# Popula o OpenLDAP com a estrutura usada pela API (idempotente: ldapadd -c ignora o que ja existe).
#   ou=usuarios  -> contas (inetOrgPerson, login = uid)
#   ou=grupos    -> cn=professores / cn=estudantes (groupOfNames) definem o perfil na API
# As senhas vem do .env (nunca versionadas) e sao gravadas como hash SSHA.
set -euo pipefail

: "${LDAP_HOST:=ldap}"
: "${LDAP_BASE_DN:=dc=enade,dc=local}"
: "${LDAP_ADMIN_PASSWORD:?defina LDAP_ADMIN_PASSWORD no .env}"
: "${LDAP_SENHA_PROFESSOR_DEMO:?defina LDAP_SENHA_PROFESSOR_DEMO no .env}"
: "${LDAP_SENHA_ESTUDANTE_DEMO:?defina LDAP_SENHA_ESTUDANTE_DEMO no .env}"

ADMIN="cn=admin,${LDAP_BASE_DN}"
URL="ldap://${LDAP_HOST}:389"

for i in $(seq 1 60); do
  ldapsearch -x -H "$URL" -D "$ADMIN" -w "$LDAP_ADMIN_PASSWORD" -b "$LDAP_BASE_DN" -s base >/dev/null 2>&1 && break
  echo "aguardando LDAP ($i)..."; sleep 2
done

SENHA_PROF=$(slappasswd -s "$LDAP_SENHA_PROFESSOR_DEMO")
SENHA_ALUNO=$(slappasswd -s "$LDAP_SENHA_ESTUDANTE_DEMO")

ldapadd -c -x -H "$URL" -D "$ADMIN" -w "$LDAP_ADMIN_PASSWORD" <<EOF || true
dn: ou=usuarios,${LDAP_BASE_DN}
objectClass: organizationalUnit
ou: usuarios

dn: ou=grupos,${LDAP_BASE_DN}
objectClass: organizationalUnit
ou: grupos

dn: uid=prof.demo,ou=usuarios,${LDAP_BASE_DN}
objectClass: inetOrgPerson
uid: prof.demo
cn: Professor Demo
sn: Demo
displayName: Professor Demo
mail: prof.demo@enade.local
userPassword: ${SENHA_PROF}

dn: uid=aluno.demo,ou=usuarios,${LDAP_BASE_DN}
objectClass: inetOrgPerson
uid: aluno.demo
cn: Estudante Demo
sn: Demo
displayName: Estudante Demo
mail: aluno.demo@enade.local
userPassword: ${SENHA_ALUNO}

dn: cn=professores,ou=grupos,${LDAP_BASE_DN}
objectClass: groupOfNames
cn: professores
member: uid=prof.demo,ou=usuarios,${LDAP_BASE_DN}

dn: cn=estudantes,ou=grupos,${LDAP_BASE_DN}
objectClass: groupOfNames
cn: estudantes
member: uid=aluno.demo,ou=usuarios,${LDAP_BASE_DN}
EOF

echo "LDAP pronto: usuarios prof.demo (professor) e aluno.demo (estudante)."
