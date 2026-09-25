"""Seguimiento de portafolios de inversión.

Capas (de abajo hacia arriba):
    core      -> cálculos financieros puros, sin base de datos ni usuarios.
    data      -> modelos SQLAlchemy, tipos y consultas (repositorios).
    services  -> casos de uso: leen la base, llaman al núcleo, devuelven resultados.
    sources   -> conectores a fuentes externas (Banrep, DANE, Superfinanciera).
    api       -> FastAPI sobre los servicios (fase multiusuario).
    ui        -> Streamlit; llama a los servicios, nunca a SQL.
"""
