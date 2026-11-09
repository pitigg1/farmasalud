-- Ejecutar en Query Tool de pgAdmin, conectado a la BD farmacia.
SELECT current_database() AS base_datos, current_user AS usuario;

SELECT m.id_medicamento,m.nombre,m.stock AS stock_fisico,v.reservado,v.disponible
FROM farmacia.medicamentos m JOIN farmacia.v_stock_disponible v USING (id_medicamento)
ORDER BY m.id_medicamento;

SELECT id_cliente,id_usuario,nombre,apellido,tipo_documento,documento
FROM farmacia.clientes ORDER BY id_cliente DESC;

SELECT p.id_pedido,p.fecha_pedido,c.nombre || ' ' || c.apellido AS cliente,
       u.correo AS empleado,p.estado,p.total
FROM farmacia.pedidos p JOIN farmacia.clientes c USING (id_cliente)
LEFT JOIN farmacia.usuarios u ON u.id_usuario=p.id_empleado ORDER BY p.id_pedido DESC;

SELECT d.id_pedido,m.nombre,d.cantidad,d.precio_unitario,d.cantidad*d.precio_unitario AS subtotal
FROM farmacia.detalles_pedido d JOIN farmacia.medicamentos m USING (id_medicamento)
WHERE d.id_pedido=(SELECT MAX(id_pedido) FROM farmacia.pedidos);

SELECT * FROM farmacia.movimientos_inventario ORDER BY id_movimiento DESC LIMIT 10;
SELECT * FROM farmacia.formulas ORDER BY id_formula DESC LIMIT 10;
SELECT id_pedido,clave_operacion,comprobante FROM farmacia.pedidos ORDER BY id_pedido DESC LIMIT 5;
