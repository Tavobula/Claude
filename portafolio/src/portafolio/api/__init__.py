"""API REST (FastAPI) para uso multiusuario.

Cada solicitud llega con un token de un proveedor de identidad (OIDC). La API
identifica al usuario, exige la autorización de tratamiento de datos y solo
deja ver y modificar sus propios portafolios. Toda la lógica está en
``portafolio.services``; aquí solo hay autenticación, autorización y
traducción entre JSON y los servicios.

Ejecutar: ``python -m portafolio api`` (ver ``api.config`` para las variables).
"""
