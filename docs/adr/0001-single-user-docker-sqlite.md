# Despliegue monolenguaje con Docker y SQLite

Status: superseded by ADR-0002

La aplicación será TypeScript de extremo a extremo y se desplegará en Docker sobre un único servidor Linux, con SQLite persistente y copia diaria. Se elige esta forma por tratarse de un único usuario, volumen reducido e histórico sencillo de respaldar; un servicio de base de datos separado añadiría operación sin aportar valor actual.
