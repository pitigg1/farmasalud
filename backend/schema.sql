DROP SCHEMA IF EXISTS farmacia CASCADE;
CREATE SCHEMA farmacia;
SET search_path TO farmacia;

CREATE TABLE usuarios (
    id_usuario     SERIAL PRIMARY KEY,
    correo         VARCHAR(100) NOT NULL UNIQUE,
    password_hash  VARCHAR(255) NOT NULL,
    rol            VARCHAR(20)  NOT NULL CHECK (rol IN ('cliente', 'empleado', 'admin')),
    activo         BOOLEAN      NOT NULL DEFAULT TRUE,
    creado_en      TIMESTAMP    NOT NULL DEFAULT NOW()
);

CREATE TABLE clientes (
    id_cliente      SERIAL PRIMARY KEY,
    id_usuario      INT UNIQUE REFERENCES usuarios(id_usuario) ON DELETE SET NULL,
    nombre          VARCHAR(100) NOT NULL,
    apellido        VARCHAR(100) NOT NULL,
    tipo_documento  VARCHAR(10)  NOT NULL DEFAULT 'CC' CHECK (tipo_documento IN ('CC', 'CE', 'TI', 'PAS', 'NIT')),
    documento       VARCHAR(20)  NOT NULL,
    correo          VARCHAR(100),
    celular         VARCHAR(20),
    creado_en       TIMESTAMP NOT NULL DEFAULT NOW(),
    UNIQUE (tipo_documento, documento)
);

CREATE TABLE laboratorios (
    id_laboratorio SERIAL PRIMARY KEY,
    nombre         VARCHAR(100) NOT NULL UNIQUE,
    pais           VARCHAR(50)
);

CREATE TABLE categorias (
    id_categoria SERIAL PRIMARY KEY,
    nombre       VARCHAR(100) NOT NULL UNIQUE
);

CREATE TABLE medicamentos (
    id_medicamento   SERIAL PRIMARY KEY,
    id_laboratorio   INT NOT NULL REFERENCES laboratorios(id_laboratorio),
    id_categoria     INT NOT NULL REFERENCES categorias(id_categoria),
    nombre           VARCHAR(150) NOT NULL,
    mg               INT CHECK (mg > 0),
    forma            VARCHAR(50),
    requiere_formula BOOLEAN NOT NULL DEFAULT FALSE,
    stock            INT NOT NULL DEFAULT 0 CHECK (stock >= 0),
    precio           NUMERIC(10,2) NOT NULL CHECK (precio >= 0),
    imagen_url       VARCHAR(255),
    activo           BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE INDEX idx_medicamentos_nombre    ON medicamentos (LOWER(nombre));
CREATE INDEX idx_medicamentos_categoria ON medicamentos (id_categoria);

CREATE TABLE pedidos (
    id_pedido        SERIAL PRIMARY KEY,
    id_cliente       INT NOT NULL REFERENCES clientes(id_cliente),
    id_empleado      INT REFERENCES usuarios(id_usuario),
    fecha_pedido     DATE NOT NULL DEFAULT CURRENT_DATE,
    estado           VARCHAR(30) NOT NULL DEFAULT 'pendiente'
                     CHECK (estado IN ('pendiente', 'confirmado', 'entregado', 'cancelado')),
    direccion_envio  VARCHAR(200),
    metodo_pago      VARCHAR(30),
    total            NUMERIC(12,2) NOT NULL DEFAULT 0 CHECK (total >= 0)
);

CREATE INDEX idx_pedidos_cliente ON pedidos (id_cliente);
CREATE INDEX idx_pedidos_estado  ON pedidos (estado);

CREATE TABLE detalles_pedido (
    id_detalle      SERIAL PRIMARY KEY,
    id_pedido       INT NOT NULL REFERENCES pedidos(id_pedido) ON DELETE CASCADE,
    id_medicamento  INT NOT NULL REFERENCES medicamentos(id_medicamento),
    cantidad        INT NOT NULL CHECK (cantidad > 0),
    precio_unitario NUMERIC(10,2) NOT NULL CHECK (precio_unitario >= 0),
    UNIQUE (id_pedido, id_medicamento)
);

CREATE TABLE formulas (
    id_formula     SERIAL PRIMARY KEY,
    id_pedido      INT NOT NULL REFERENCES pedidos(id_pedido) ON DELETE CASCADE,
    id_medicamento INT NOT NULL REFERENCES medicamentos(id_medicamento),
    medico         VARCHAR(100) NOT NULL,
    numero_formula VARCHAR(50)  NOT NULL,
    fecha_emision  DATE NOT NULL,
    fecha_vence    DATE NOT NULL,
    valida         BOOLEAN NOT NULL DEFAULT FALSE,
    CHECK (fecha_vence >= fecha_emision)
);

CREATE TABLE reservas (
    id_reserva      SERIAL PRIMARY KEY,
    id_cliente      INT NOT NULL REFERENCES clientes(id_cliente),
    id_medicamento  INT NOT NULL REFERENCES medicamentos(id_medicamento),
    id_pedido       INT REFERENCES pedidos(id_pedido) ON DELETE SET NULL,
    cantidad        INT NOT NULL CHECK (cantidad > 0),
    estado          VARCHAR(20) NOT NULL DEFAULT 'activa' CHECK (estado IN ('activa', 'consumida', 'no_activa')),
    creada_en       TIMESTAMP NOT NULL DEFAULT NOW(),
    expira_en       TIMESTAMP NOT NULL DEFAULT (NOW() + INTERVAL '15 minutes')
);

CREATE INDEX idx_reservas_activas ON reservas (id_medicamento) WHERE estado = 'activa';

CREATE TABLE movimientos_inventario (
    id_movimiento  SERIAL PRIMARY KEY,
    id_medicamento INT NOT NULL REFERENCES medicamentos(id_medicamento),
    id_usuario     INT REFERENCES usuarios(id_usuario),
    tipo           VARCHAR(20) NOT NULL CHECK (tipo IN ('entrada', 'salida', 'ajuste')),
    cantidad       INT NOT NULL,
    motivo         VARCHAR(200),
    fecha          TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE VIEW v_stock_disponible AS
SELECT m.id_medicamento,
       m.nombre,
       m.stock AS stock_fisico,
       COALESCE(SUM(r.cantidad) FILTER (WHERE r.estado = 'activa' AND r.expira_en > NOW()), 0) AS reservado,
       m.stock - COALESCE(SUM(r.cantidad) FILTER (WHERE r.estado = 'activa' AND r.expira_en > NOW()), 0) AS disponible
FROM medicamentos m
LEFT JOIN reservas r ON r.id_medicamento = m.id_medicamento
GROUP BY m.id_medicamento;

CREATE VIEW v_catalogo AS
SELECT m.id_medicamento, m.nombre, m.mg, m.forma, m.precio, m.imagen_url,
       m.requiere_formula, c.nombre AS categoria, l.nombre AS laboratorio,
       v.disponible
FROM medicamentos m
JOIN categorias c   ON c.id_categoria = m.id_categoria
JOIN laboratorios l ON l.id_laboratorio = m.id_laboratorio
JOIN v_stock_disponible v ON v.id_medicamento = m.id_medicamento
WHERE m.activo;

CREATE VIEW v_mas_vendidos AS
SELECT m.id_medicamento, m.nombre, SUM(d.cantidad) AS unidades_vendidas
FROM detalles_pedido d
JOIN pedidos p      ON p.id_pedido = d.id_pedido AND p.estado IN ('confirmado', 'entregado')
JOIN medicamentos m ON m.id_medicamento = d.id_medicamento
GROUP BY m.id_medicamento
ORDER BY unidades_vendidas DESC;

CREATE VIEW v_historial_pedidos AS
SELECT p.id_pedido, p.id_cliente, p.fecha_pedido, p.estado, p.total,
       COUNT(d.id_detalle) AS items
FROM pedidos p
LEFT JOIN detalles_pedido d ON d.id_pedido = p.id_pedido
GROUP BY p.id_pedido;

CREATE OR REPLACE FUNCTION reservar_stock(p_cliente INT, p_medicamento INT, p_cantidad INT)
RETURNS INT AS $$
DECLARE
    v_disponible INT;
    v_id INT;
BEGIN
    PERFORM 1 FROM medicamentos WHERE id_medicamento = p_medicamento FOR UPDATE;

    SELECT disponible INTO v_disponible
    FROM v_stock_disponible WHERE id_medicamento = p_medicamento;

    IF v_disponible IS NULL OR v_disponible < p_cantidad THEN
        RAISE EXCEPTION 'Stock insuficiente (disponible: %)', COALESCE(v_disponible, 0);
    END IF;

    INSERT INTO reservas (id_cliente, id_medicamento, cantidad)
    VALUES (p_cliente, p_medicamento, p_cantidad)
    RETURNING id_reserva INTO v_id;

    RETURN v_id;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION confirmar_pedido(
    p_cliente INT, p_empleado INT DEFAULT NULL,
    p_direccion VARCHAR DEFAULT NULL, p_metodo_pago VARCHAR DEFAULT NULL)
RETURNS INT AS $$
DECLARE
    v_pedido INT;
    r RECORD;
BEGIN
    IF NOT EXISTS (SELECT 1 FROM reservas
                   WHERE id_cliente = p_cliente AND estado = 'activa' AND expira_en > NOW()) THEN
        RAISE EXCEPTION 'El cliente no tiene reservas activas';
    END IF;

    INSERT INTO pedidos (id_cliente, id_empleado, estado, direccion_envio, metodo_pago)
    VALUES (p_cliente, p_empleado, 'confirmado', p_direccion, p_metodo_pago)
    RETURNING id_pedido INTO v_pedido;

    FOR r IN
        SELECT re.id_reserva, re.id_medicamento, re.cantidad, m.precio
        FROM reservas re JOIN medicamentos m USING (id_medicamento)
        WHERE re.id_cliente = p_cliente AND re.estado = 'activa' AND re.expira_en > NOW()
    LOOP
        INSERT INTO detalles_pedido (id_pedido, id_medicamento, cantidad, precio_unitario)
        VALUES (v_pedido, r.id_medicamento, r.cantidad, r.precio);

        UPDATE medicamentos SET stock = stock - r.cantidad
        WHERE id_medicamento = r.id_medicamento;

        UPDATE reservas SET estado = 'consumida', id_pedido = v_pedido
        WHERE id_reserva = r.id_reserva;

        INSERT INTO movimientos_inventario (id_medicamento, id_usuario, tipo, cantidad, motivo)
        VALUES (r.id_medicamento, p_empleado, 'salida', r.cantidad, 'Pedido #' || v_pedido);
    END LOOP;

    UPDATE pedidos
    SET total = (SELECT SUM(cantidad * precio_unitario) FROM detalles_pedido WHERE id_pedido = v_pedido)
    WHERE id_pedido = v_pedido;

    RETURN v_pedido;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION liberar_reservas_vencidas() RETURNS INT AS $$
DECLARE n INT;
BEGIN
    UPDATE reservas SET estado = 'no_activa'
    WHERE estado = 'activa' AND expira_en <= NOW();
    GET DIAGNOSTICS n = ROW_COUNT;
    RETURN n;
END;
$$ LANGUAGE plpgsql;

INSERT INTO laboratorios (nombre, pais) VALUES
 ('Genfar', 'Colombia'), ('Bayer', 'Alemania'), ('Pfizer', 'Estados Unidos');

INSERT INTO categorias (nombre) VALUES
 ('Analgésicos'), ('Antibióticos'), ('Antihistamínicos'), ('Vitaminas');

INSERT INTO medicamentos (id_laboratorio, id_categoria, nombre, mg, forma, requiere_formula, stock, precio) VALUES
 (1, 1, 'Acetaminofén', 500, 'Tableta', FALSE, 200, 3500),
 (2, 1, 'Aspirina',     100, 'Tableta', FALSE, 150, 5200),
 (3, 2, 'Amoxicilina',  500, 'Cápsula', TRUE,   80, 12900),
 (1, 3, 'Loratadina',    10, 'Tableta', FALSE, 120, 4800),
 (2, 4, 'Vitamina C',  1000, 'Efervescente', FALSE, 60, 9900);

INSERT INTO usuarios (correo, password_hash, rol) VALUES
 ('admin@farmacia.com',    'REEMPLAZAR_POR_HASH', 'admin'),
 ('empleado@farmacia.com', 'REEMPLAZAR_POR_HASH', 'empleado'),
 ('cliente@mail.com',      'REEMPLAZAR_POR_HASH', 'cliente');

INSERT INTO clientes (id_usuario, nombre, apellido, tipo_documento, documento, correo, celular) VALUES
 (3, 'Laura', 'Gómez', 'CC', '1098765432', 'cliente@mail.com', '3001234567');
