-- =============================================================================
--  Esquema `contratos` en la base cmg_cen: contratos de suministro del CEN
-- =============================================================================
--
-- Vive en la MISMA base de cmg-ingesta (cmg_cen, decisión del usuario 2026-10-15), en su
-- propio esquema. Las mismas dos tablas de Silver (contratos-ingesta):
--
--     contratos.contrato        un contrato (TODOS; filtrar por `vigente`)
--     contratos.contrato_barra  un punto de retiro o suministro de un contrato
--     contratos.carga           una fila por cada carga hecha (control y auditoría)
--
-- Usuarios:
--     contratos_carga  escribe SOLO en el esquema `contratos` (no puede tocar `cmg`)
--     cmg_lectura      el lector que ya existe en cmg_cen: también lee `contratos`
--
-- La llena el comando `contratos publicar-sql`; más adelante la consultará una API.
--
-- Cómo correrlo (UNA vez, con un usuario administrador):
--
--     psql -h 192.168.0.85 -p 5433 -U postgres -d cmg_cen -f sql/esquema_contratos.sql
--
-- Se puede volver a correr sin romper nada (todo es "si no existe").
-- Después, la clave del usuario nuevo (NO va en este archivo, que va a git):
--
--     \password contratos_carga      -- la usa `contratos publicar-sql`

BEGIN;

-- ------------------------------------------------------------------ usuarios

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'contratos_carga') THEN
        CREATE ROLE contratos_carga LOGIN;
    END IF;
    -- cmg_lectura lo crea sql/cmg_cen.sql de cmg-ingesta; sin él, no hay a quién dar lectura
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cmg_lectura') THEN
        RAISE EXCEPTION 'falta el usuario cmg_lectura: ¿es la base cmg_cen?';
    END IF;
END
$$;

-- Todo vive en el esquema `contratos`, cuyo dueño es contratos_carga.
CREATE SCHEMA IF NOT EXISTS contratos AUTHORIZATION contratos_carga;
GRANT USAGE ON SCHEMA contratos TO cmg_lectura;
DO $$ BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO contratos_carga',
                   current_database());
END $$;

SET ROLE contratos_carga;  -- lo que sigue queda a nombre de contratos_carga

-- La lectura ve todo lo que cree la carga, también lo que se agregue en el futuro.
ALTER DEFAULT PRIVILEGES IN SCHEMA contratos GRANT SELECT ON TABLES TO cmg_lectura;

-- ------------------------------------------------------------------ tablas

CREATE TABLE IF NOT EXISTS contratos.contrato (
    id_contrato                 text PRIMARY KEY,
    suministrador               text,
    rut_suministrador           text,
    tipo_suministrador          text,
    tipo_contrato               text,
    red_distribuidora           text,
    tipo_cliente                text,
    cliente                     text,
    rut_cliente                 text,
    estado_fuente               text,          -- 'Estado Contrato' tal como lo publica el CEN
    region                      text,
    sector_economico            text,
    subsector_economico         text,
    fecha_suscripcion           date,
    fecha_inicio                date,
    fecha_termino               date,
    fecha_termino_renovacion    date,
    fecha_termino_efectiva      date,          -- el mayor entre término y término de renovación
    vigente                     boolean NOT NULL,  -- manda la fecha
    estado_distinto             boolean NOT NULL,  -- 'Estado Contrato' dice otra cosa
    dias_para_vencer            integer,
    energia_max_anual_gwh       double precision NOT NULL,  -- RN-05: la energía del contrato
    energia_promedio_anual_gwh  double precision NOT NULL,
    energia_min_anual_gwh       double precision NOT NULL,
    anios_energia               text,          -- años usados, separados por coma
    anios_aislados              text,          -- años excluidos por RN-07
    potencia_max_anual_mw       double precision NOT NULL,
    fecha_datos                 date NOT NULL, -- fecha del Excel del CEN que se cargó
    fecha_ingreso               date NOT NULL  -- primer día en que el contrato entró a la base
);

CREATE TABLE IF NOT EXISTS contratos.contrato_barra (
    id_contrato  text NOT NULL REFERENCES contratos.contrato (id_contrato) ON DELETE CASCADE,
    tipo_punto   text NOT NULL CHECK (tipo_punto IN ('retiro', 'suministro')),
    orden        smallint NOT NULL,
    texto        text NOT NULL,                -- el punto tal como venía
    subestacion  text NOT NULL,
    propietario  text,
    tension_kv   double precision,
    seccion      text,
    reconocido   boolean NOT NULL,             -- false = forma desconocida (texto completo)
    PRIMARY KEY (id_contrato, tipo_punto, orden)
);

CREATE INDEX IF NOT EXISTS contrato_barra_subestacion ON contratos.contrato_barra (subestacion);
CREATE INDEX IF NOT EXISTS contrato_suministrador ON contratos.contrato (suministrador);

-- Una fila por carga: qué archivo de Silver se subió, cuándo y cuántas filas.
CREATE TABLE IF NOT EXISTS contratos.carga (
    carga_id        integer GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    fecha_datos     date NOT NULL,
    archivo_origen  text NOT NULL,              -- el Excel de Bronze que originó Silver
    sha256_silver   text NOT NULL,              -- huella de contratos.parquet + contrato_barra.parquet
    contratos       integer NOT NULL,
    puntos          integer NOT NULL,
    cargado_en      timestamptz NOT NULL DEFAULT now()
);

RESET ROLE;
COMMIT;
