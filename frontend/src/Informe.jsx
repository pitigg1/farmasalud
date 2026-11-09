import { useEffect, useState } from 'react'
import { api } from './api'

const fmt = n => '$' + Number(n).toLocaleString('es-CO')
const iso = d => d.toLocaleDateString('en-CA')  // AAAA-MM-DD en hora local

// Caso de uso "Generar Informe de Inventario/Ventas". Usa los estilos de impresión del comprobante.
export function Informe({ auth, close }) {
  const hoy = new Date()
  const [desde, setDesde] = useState(iso(new Date(hoy.getFullYear(), hoy.getMonth(), hoy.getDate() - 29)))
  const [hasta, setHasta] = useState(iso(hoy))
  const [umbral, setUmbral] = useState(10)
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const generar = async e => {
    e?.preventDefault(); setBusy(true); setError('')
    try { setData(await api('/informes?' + new URLSearchParams({ desde, hasta, umbral }), { token: auth.token })) }
    catch (x) { setError(x.message) } finally { setBusy(false) }
  }
  useEffect(() => { generar() }, [])
  const v = data?.ventas, inv = data?.inventario

  return <div className="scrim receipt-overlay"><article className="modal w receipt" role="dialog" aria-modal="true" aria-label="Informe de inventario y ventas">
    <div className="no-print section-head"><button className="link" onClick={close}>Cerrar informe</button>{data && <button className="yel" onClick={() => window.print()}>Imprimir / Guardar PDF</button>}</div>
    <form className="no-print fgrid" onSubmit={generar}>
      <div><label htmlFor="i-desde">Desde</label><input id="i-desde" type="date" required value={desde} max={hasta} onChange={e => setDesde(e.target.value)} /></div>
      <div><label htmlFor="i-hasta">Hasta</label><input id="i-hasta" type="date" required value={hasta} min={desde} onChange={e => setHasta(e.target.value)} /></div>
      <div><label htmlFor="i-umbral">Alerta de stock bajo (≤)</label><input id="i-umbral" type="number" min="0" step="1" required value={umbral} onChange={e => setUmbral(e.target.value)} /></div>
      <button className="yel" disabled={busy}>{busy ? 'Generando…' : 'Generar informe'}</button>
    </form>
    <p className="err" role="alert">{error}</p>
    {data && <>
      <h2>Informe de inventario y ventas · FarmaSalud</h2>
      <p className="mute">Periodo {data.periodo.desde} a {data.periodo.hasta} · generado {new Date(data.generado_en).toLocaleString('es-CO')} por {data.generado_por}</p>

      <h3>Ventas del periodo</h3>
      <div className="stats">
        <div className="st"><div><small>Total vendido</small><b>{fmt(v.resumen.total_vendido)}</b></div></div>
        <div className="st"><div><small>Pedidos</small><b>{v.resumen.pedidos}</b></div></div>
        <div className="st"><div><small>Unidades vendidas</small><b>{v.resumen.unidades}</b></div></div>
        <div className="st"><div><small>Ticket promedio</small><b>{fmt(v.resumen.ticket_promedio)}</b></div></div>
      </div>
      {v.resumen.pedidos === 0 ? <p className="mute">No hay ventas confirmadas en este periodo.</p> : <>
        <h3>Medicamentos más vendidos</h3>
        <div className="table-scroll"><table><thead><tr><th>#</th><th>Medicamento</th><th>Unidades</th><th>Ingresos</th></tr></thead>
          <tbody>{v.mas_vendidos.map((m, i) => <tr key={m.id_medicamento}><td>{i + 1}</td><td>{m.nombre}</td><td>{m.unidades}</td><td>{fmt(m.ingresos)}</td></tr>)}</tbody></table></div>
        <div className="two">
          <div><h3>Por canal</h3><table><thead><tr><th>Canal</th><th>Pedidos</th><th>Total</th></tr></thead>
            <tbody>{v.por_canal.map(c => <tr key={c.canal}><td>{c.canal}</td><td>{c.pedidos}</td><td>{fmt(c.total)}</td></tr>)}</tbody></table></div>
          <div><h3>Por método de pago</h3><table><thead><tr><th>Método</th><th>Pedidos</th><th>Total</th></tr></thead>
            <tbody>{v.por_metodo_pago.map(c => <tr key={c.metodo_pago}><td>{c.metodo_pago}</td><td>{c.pedidos}</td><td>{fmt(c.total)}</td></tr>)}</tbody></table></div>
        </div>
        <h3>Ventas por día</h3>
        <div className="table-scroll"><table><thead><tr><th>Fecha</th><th>Pedidos</th><th>Total</th></tr></thead>
          <tbody>{v.por_dia.map(d => <tr key={d.fecha}><td>{d.fecha}</td><td>{d.pedidos}</td><td>{fmt(d.total)}</td></tr>)}</tbody></table></div>
      </>}

      <h3>Inventario actual</h3>
      <div className="stats">
        <div className="st"><div><small>Medicamentos activos</small><b>{inv.productos}</b></div></div>
        <div className="st"><div><small>Unidades en stock</small><b>{inv.unidades}</b></div></div>
        <div className="st"><div><small>Valor del inventario</small><b>{fmt(inv.valor_total)}</b></div></div>
        <div className="st"><div><small>Con stock bajo</small><b>{inv.bajo_stock}</b></div></div>
      </div>
      <div className="table-scroll"><table><thead><tr><th>Medicamento</th><th>Categoría</th><th>Precio</th><th>Stock físico</th><th>Disponible</th><th>Valor</th><th>Estado</th></tr></thead>
        <tbody>{inv.detalle.map(m => <tr key={m.id_medicamento}><td>{m.nombre}</td><td>{m.categoria}</td><td>{fmt(m.precio)}</td><td>{m.stock_fisico}</td><td>{m.disponible}</td><td>{fmt(m.valor)}</td>
          <td>{m.bajo_stock ? <span className="est" style={{ background: '#FEF3C7', color: '#B45309', whiteSpace: 'nowrap' }}>Stock bajo</span> : <span className="est">Normal</span>}</td></tr>)}</tbody></table></div>
      <p className="mute">Solo se cuentan pedidos confirmados o entregados. Los valores se calculan en PostgreSQL.</p>
    </>}
  </article></div>
}
