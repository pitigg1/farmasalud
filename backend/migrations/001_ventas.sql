-- Ejecutar sobre la BD existente. No borra tablas, clientes, stock ni ventas.
BEGIN;
SET LOCAL search_path TO farmacia, public;
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS clave_operacion UUID;
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS id_usuario_operacion INT REFERENCES usuarios(id_usuario);
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS solicitud_hash VARCHAR(64);
ALTER TABLE pedidos ADD COLUMN IF NOT EXISTS comprobante JSONB;
CREATE UNIQUE INDEX IF NOT EXISTS idx_pedidos_operacion ON pedidos (clave_operacion);

CREATE OR REPLACE FUNCTION snapshot_pedido(p_id INT) RETURNS JSONB AS $$
SELECT jsonb_build_object(
    'id_pedido',p.id_pedido,'numero','FS-' || p.id_pedido,'fecha',p.fecha_pedido,
    'estado',p.estado,'total',p.total::TEXT,'metodo_pago',p.metodo_pago,
    'direccion',p.direccion_envio,'empleado',u.correo,
    'cliente',jsonb_build_object('id_cliente',c.id_cliente,'nombre',c.nombre || ' ' || c.apellido,
        'tipo_documento',c.tipo_documento,'documento',c.documento,'correo',c.correo,'celular',c.celular),
    'items',COALESCE((SELECT jsonb_agg(jsonb_build_object(
        'id_medicamento',d.id_medicamento,'nombre',m.nombre || COALESCE(' ' || m.mg || 'mg',''),
        'cantidad',d.cantidad,'precio',d.precio_unitario::TEXT,
        'subtotal',(d.cantidad*d.precio_unitario)::TEXT) ORDER BY d.id_medicamento)
        FROM detalles_pedido d JOIN medicamentos m USING (id_medicamento)
        WHERE d.id_pedido=p.id_pedido),'[]'::JSONB))
FROM pedidos p JOIN clientes c USING (id_cliente)
LEFT JOIN usuarios u ON u.id_usuario=p.id_empleado WHERE p.id_pedido=p_id;
$$ LANGUAGE SQL SET search_path = farmacia, public;

-- Los pedidos anteriores reciben una copia con los datos disponibles al migrar.
UPDATE pedidos SET comprobante=snapshot_pedido(id_pedido) WHERE comprobante IS NULL;

CREATE OR REPLACE FUNCTION reservar_stock(p_cliente INT,p_medicamento INT,p_cantidad INT)
RETURNS INT AS $$
DECLARE v_disponible INT; v_id INT;
BEGIN
    IF p_cantidad IS NULL OR p_cantidad <= 0 THEN RAISE EXCEPTION 'Cantidad inválida'; END IF;
    PERFORM 1 FROM clientes WHERE id_cliente=p_cliente FOR UPDATE;
    PERFORM 1 FROM medicamentos WHERE id_medicamento=p_medicamento AND activo FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Medicamento no disponible'; END IF;
    SELECT disponible INTO v_disponible FROM v_stock_disponible WHERE id_medicamento=p_medicamento;
    IF v_disponible < p_cantidad THEN
        RAISE EXCEPTION 'Stock insuficiente (disponible: %)',v_disponible;
    END IF;
    INSERT INTO reservas (id_cliente,id_medicamento,cantidad)
    VALUES (p_cliente,p_medicamento,p_cantidad) RETURNING id_reserva INTO v_id;
    RETURN v_id;
END;
$$ LANGUAGE plpgsql SET search_path = farmacia, public;

-- Se reemplaza la firma anterior para exigir el nuevo camino de validación.
DROP FUNCTION IF EXISTS confirmar_pedido(INT,INT,VARCHAR,VARCHAR);
CREATE OR REPLACE FUNCTION confirmar_pedido(
    p_cliente INT,p_empleado INT,p_direccion VARCHAR,p_metodo_pago VARCHAR,p_formulas JSONB)
RETURNS INT AS $$
DECLARE v_pedido INT; r RECORD; f JSONB;
BEGIN
    PERFORM 1 FROM clientes WHERE id_cliente=p_cliente FOR UPDATE;
    IF p_empleado IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM usuarios WHERE id_usuario=p_empleado AND rol='empleado' AND activo) THEN
        RAISE EXCEPTION 'Empleado inválido';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM reservas WHERE id_cliente=p_cliente
                   AND estado='activa' AND expira_en>NOW()) THEN
        RAISE EXCEPTION 'El cliente no tiene reservas activas';
    END IF;
    -- Orden fijo también en SQL; protege llamados directos a la función.
    PERFORM m.id_medicamento FROM medicamentos m WHERE m.id_medicamento IN (
        SELECT id_medicamento FROM reservas WHERE id_cliente=p_cliente
        AND estado='activa' AND expira_en>NOW()) ORDER BY m.id_medicamento FOR UPDATE;
    INSERT INTO pedidos (id_cliente,id_empleado,estado,direccion_envio,metodo_pago)
    VALUES (p_cliente,p_empleado,'confirmado',p_direccion,p_metodo_pago)
    RETURNING id_pedido INTO v_pedido;
    FOR r IN SELECT re.id_reserva,re.id_medicamento,re.cantidad,m.precio,m.requiere_formula,m.activo
             FROM reservas re JOIN medicamentos m USING (id_medicamento)
             WHERE re.id_cliente=p_cliente AND re.estado='activa' AND re.expira_en>NOW()
             ORDER BY re.id_medicamento,re.id_reserva FOR UPDATE OF re
    LOOP
        IF NOT r.activo THEN RAISE EXCEPTION 'Medicamento no disponible'; END IF;
        IF r.requiere_formula THEN
            SELECT value INTO f FROM jsonb_array_elements(p_formulas)
            WHERE (value->>'id_medicamento')::INT=r.id_medicamento;
            IF p_empleado IS NULL OR f IS NULL OR NOT COALESCE((f->>'formula_verificada')::BOOLEAN,FALSE)
               OR COALESCE(BTRIM(f->>'numero_formula'),'')='' OR COALESCE(BTRIM(f->>'medico'),'')=''
               OR f->>'fecha_emision' IS NULL OR f->>'fecha_vence' IS NULL
               OR (f->>'fecha_emision')::DATE>CURRENT_DATE OR (f->>'fecha_vence')::DATE<CURRENT_DATE THEN
                RAISE EXCEPTION 'Se requiere fórmula vigente verificada por el empleado';
            END IF;
            -- La verificación queda registrada antes del descuento, dentro de la misma transacción.
            INSERT INTO formulas (id_pedido,id_medicamento,medico,numero_formula,fecha_emision,fecha_vence,valida)
            VALUES (v_pedido,r.id_medicamento,f->>'medico',f->>'numero_formula',
                    (f->>'fecha_emision')::DATE,(f->>'fecha_vence')::DATE,TRUE);
        END IF;
        UPDATE medicamentos SET stock=stock-r.cantidad
        WHERE id_medicamento=r.id_medicamento AND stock>=r.cantidad;
        IF NOT FOUND THEN RAISE EXCEPTION 'Stock insuficiente'; END IF;
        INSERT INTO detalles_pedido (id_pedido,id_medicamento,cantidad,precio_unitario)
        VALUES (v_pedido,r.id_medicamento,r.cantidad,r.precio);
        UPDATE reservas SET estado='consumida',id_pedido=v_pedido WHERE id_reserva=r.id_reserva;
        INSERT INTO movimientos_inventario (id_medicamento,id_usuario,tipo,cantidad,motivo)
        VALUES (r.id_medicamento,p_empleado,'salida',r.cantidad,'Pedido #' || v_pedido);
    END LOOP;
    UPDATE pedidos SET total=(SELECT SUM(cantidad*precio_unitario) FROM detalles_pedido
                              WHERE id_pedido=v_pedido) WHERE id_pedido=v_pedido;
    RETURN v_pedido;
END;
$$ LANGUAGE plpgsql SET search_path = farmacia, public;
COMMIT;
