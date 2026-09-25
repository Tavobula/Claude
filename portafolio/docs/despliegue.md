# Despliegue multiusuario

Este documento cubre cómo abrir el servicio a otras personas. Para uso
personal no hace falta nada de esto: basta la interfaz Streamlit con SQLite.

> Antes de invitar a otra persona, complete y haga revisar por un abogado la
> política de tratamiento de datos (`src/portafolio/api/politica_tratamiento_datos.md`).
> La herramienta es de seguimiento y cálculo, **no de asesoría de inversión**,
> que en Colombia es una actividad regulada.

## Arquitectura

```
Internet ──HTTPS──> Caddy ──> API (FastAPI) ──> PostgreSQL
                                                  │
                                    respaldo diario (pg_dump)
```

- **Caddy** obtiene y renueva el certificado TLS y es lo único expuesto
  (puertos 80 y 443).
- **API**: sin contraseñas propias; valida tokens de un proveedor OIDC.
- **PostgreSQL** solo es accesible desde la red interna de Docker.
- **Streamlit no se despliega**: no tiene ingreso de usuarios y se niega a
  correr con `PORTAFOLIO_ENTORNO=produccion`. Un frontend web para varios
  usuarios debe construirse sobre la API.

## 1. Proveedor de identidad (OIDC)

Use un proveedor administrado (Auth0, Keycloak, Microsoft Entra ID, AWS
Cognito, Google Identity Platform…). En él:

1. Registre una **API** (o "resource server") y anote su identificador: es la
   audiencia (`PORTAFOLIO_OIDC_AUDIENCIA`).
2. Anote el emisor (`iss` de los tokens): `PORTAFOLIO_OIDC_EMISOR`.
3. Registre la aplicación cliente (el frontend) con el flujo Authorization
   Code + PKCE, y pida tokens de acceso para esa audiencia.
4. Si el proveedor incluye `email` y `email_verified` en el token de acceso,
   la API los usa para el correo del usuario; si no, crea un identificador
   interno. **Nunca** vincula cuentas solo porque coincide el correo.

La API descubre las llaves en `<emisor>/.well-known/openid-configuration`; si
su proveedor no publica ese documento, defina `PORTAFOLIO_OIDC_JWKS_URL`.

## 2. Servidor

Requisitos: un servidor con Docker y Docker Compose, un dominio apuntando a él
y los puertos 80/443 abiertos.

```bash
git clone <repositorio> && cd <repositorio>/portafolio
cp .env.ejemplo .env        # complete dominio, clave de PostgreSQL y datos OIDC
chmod 600 .env
docker compose up -d --build
docker compose logs -f migrar api
curl https://<dominio>/salud
```

Si el servidor está detrás de un proxy corporativo que inspecciona HTTPS,
construya con `docker build --secret id=ca_extra,src=/ruta/ca.crt .`.

## 3. Primer administrador

Los datos globales (UVR, IPC, IBR, TRM, FIC y parámetros como la retención)
son compartidos: solo un administrador los carga.

1. Ingrese una vez a la API con su cuenta (p. ej. `GET /v1/yo`) para que se
   cree su usuario.
2. Désele el rol:

   ```bash
   docker compose exec api python -m portafolio usuarios listar
   docker compose exec api python -m portafolio usuarios admin su-correo@ejemplo.com
   ```

3. Cargue los parámetros y las series con `POST /v1/parametros/importar` y
   `POST /v1/series/{codigo}/importar`.

**Si ya usaba el modo personal**, restaure su base en PostgreSQL y vincule su
usuario existente a su identidad del proveedor (en lugar de crear uno nuevo):

```bash
docker compose exec api python -m portafolio usuarios vincular su-correo@ejemplo.com \
  --emisor https://su-proveedor.ejemplo.com/ --sujeto "<claim sub de su usuario>"
```

## 4. Respaldos

El servicio `respaldo` guarda un `pg_dump` diario en `./respaldos` y borra los
de más de `DIAS_RETENCION_RESPALDOS` días.

- **Copie los respaldos fuera del servidor y cifrados** (p. ej. con `age` o
  `gpg` hacia un almacenamiento de objetos). Un respaldo en el mismo disco no
  sirve si se pierde el servidor.
- **Pruebe la restauración** al menos cada trimestre:

  ```bash
  createdb -h <host> -U portafolio restauracion
  pg_restore -h <host> -U portafolio -d restauracion respaldos/portafolio-AAAAMMDD-HHMM.dump
  ```

## 5. Cifrado y seguridad

- **En tránsito:** HTTPS con HSTS (Caddy). La base no se expone.
- **En reposo:** use un disco cifrado (la mayoría de proveedores de nube lo
  ofrece por defecto) o un PostgreSQL administrado con cifrado en reposo.
  Los respaldos, cifrados antes de salir del servidor.
- **Secretos:** solo en `.env` (permisos 600) o en el gestor de secretos del
  proveedor. Nunca en el repositorio.
- La API responde con `Cache-Control: no-store`, no guarda contraseñas ni
  credenciales bancarias, y un recurso de otro usuario responde 404.
- Limite solicitudes por IP en el proxy o en el balanceador si el servicio
  queda abierto a internet.

## 6. Protección de datos (Ley 1581 de 2012)

Lista de verificación antes de abrir el servicio:

- [ ] Política de tratamiento completada, revisada y publicada
      (`GET /v1/politica`). Si la cambia, suba `PORTAFOLIO_POLITICA_VERSION`:
      la API pedirá aceptarla de nuevo.
- [ ] Autorización previa: la API no deja usar datos financieros sin
      `POST /v1/yo/autorizacion`, y guarda fecha y versión como prueba.
- [ ] Canal de consultas y reclamos (correo) con los plazos de la política.
- [ ] Derechos del titular: `GET /v1/yo/datos` (conocer) y
      `DELETE /v1/yo?confirmar=true` (suprimir) funcionan sin intervención.
- [ ] Contrato con el proveedor de alojamiento como encargado del tratamiento;
      si los datos quedan fuera de Colombia, evalúe la transferencia
      internacional.
- [ ] Verifique si debe inscribir la base en el Registro Nacional de Bases de
      Datos (RNBD) de la Superintendencia de Industria y Comercio.
- [ ] Aviso de que la herramienta no es asesoría de inversión, visible en el
      frontend.

## 7. Actualizaciones

```bash
git pull
docker compose up -d --build     # "migrar" aplica las migraciones nuevas antes de la API
```

Respalde antes de actualizar. Las migraciones se probaron hacia arriba y hacia
abajo en PostgreSQL 16.
