import { useEffect, useRef, useState } from 'react'
import { api } from './api'

const fmt = n => '$' + Number(n).toLocaleString('es-CO')
const emptyClient = { tipo_documento: 'CC', documento: '', nombre: '', apellido: '', correo: '', celular: '' }
const message = x => x.message || 'No se pudo completar la solicitud.'

function ClientFields({ value, onChange, lockedDocument = false }) {
  const field = (key, label, type = 'text', maxLength = 100) => <div key={key}><label htmlFor={'cli-' + key}>{label}</label><input id={'cli-' + key} required type={type} maxLength={maxLength} value={value[key]} disabled={lockedDocument && key === 'documento'} onChange={e => onChange({ ...value, [key]: e.target.value })} /></div>
  return <div className="two">
    <div><label htmlFor="cli-tipo">Tipo de documento</label><select id="cli-tipo" disabled={lockedDocument} value={value.tipo_documento} onChange={e => onChange({ ...value, tipo_documento: e.target.value })}>{['CC', 'CE', 'TI', 'PAS', 'NIT'].map(x => <option key={x}>{x}</option>)}</select></div>
    {field('documento', 'Documento', 'text', 20)}{field('nombre', 'Nombre')}{field('apellido', 'Apellido')}{field('correo', 'Correo', 'email')}{field('celular', 'Celular', 'tel', 20)}
  </div>
}

// Se conserva la clave para reintentar el mismo contenido sin duplicar la venta.
function useSale(auth, onDone, reload) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const attempt = useRef(null)
  const sending = useRef(false)
  const submit = async body => {
    if (sending.current) return
    const signature = JSON.stringify(body)
    if (attempt.current?.signature !== signature) attempt.current = { signature, key: crypto.randomUUID() }
    sending.current = true; setBusy(true); setError('')
    try {
      const sale = await api('/pedidos', { method: 'POST', token: auth.token, body: { ...body, clave_operacion: attempt.current.key } })
      attempt.current = null
      onDone(sale)
    } catch (x) { setError(message(x)); reload() }
    finally { sending.current = false; setBusy(false) }
  }
  return { submit, busy, error }
}

export function Checkout({ ids, cart, med, auth, close, onDone, reload }) {
  const [client, setClient] = useState({ ...emptyClient, correo: auth.correo })
  const [known, setKnown] = useState(false)
  const [ready, setReady] = useState(false)
  const [loadError, setLoadError] = useState('')
  const [address, setAddress] = useState('')
  const [payment, setPayment] = useState('Efectivo')
  const sale = useSale(auth, onDone, reload)
  const load = () => { setLoadError(''); api('/clientes/yo', { token: auth.token }).then(c => {
    if (c) { setKnown(true); setClient(Object.fromEntries(Object.keys(emptyClient).map(k => [k, c[k] || '']))) }
    setReady(true)
  }).catch(x => setLoadError(message(x))) }
  useEffect(load, [auth.token])
  return <div className="scrim"><form className="modal w" onSubmit={e => { e.preventDefault(); sale.submit({ cliente: client, direccion: address, metodo_pago: payment, items: ids.map(id => ({ id_medicamento: +id, cantidad: cart[id] })) }) }}>
    <button type="button" className="x" disabled={sale.busy} onClick={close} aria-label="Cerrar">×</button><h2>Finalizar compra</h2>
    {loadError && <p className="err">{loadError} <button type="button" onClick={load}>Reintentar</button></p>}
    {!ready ? <p>Cargando perfil…</p> : <fieldset disabled={sale.busy}><ClientFields value={client} onChange={setClient} lockedDocument={known} />
      <label htmlFor="address">Dirección de entrega</label><input id="address" required maxLength={200} value={address} onChange={e => setAddress(e.target.value)} />
      <Payment value={payment} onChange={setPayment} />
      <div className="totbox"><span>Total de productos</span><b>{fmt(ids.reduce((s, id) => s + Number(med(id)?.precio || 0) * cart[id], 0))}</b></div>
      <p className="mute">El total definitivo se calcula en PostgreSQL. No se procesa un pago electrónico.</p>
      <p className="err" role="alert">{sale.error}</p><button className="yel full" disabled={sale.busy}>{sale.busy ? 'Confirmando…' : 'Confirmar compra'}</button>
    </fieldset>}
  </form></div>
}

function Payment({ value, onChange }) {
  return <><label htmlFor="payment">Método de pago registrado</label><select id="payment" value={value} onChange={e => onChange(e.target.value)}>{['Efectivo', 'Datafono', 'Nequi/PSE'].map(p => <option key={p}>{p}</option>)}</select></>
}

const ESTADO_COLOR = { confirmado: null, entregado: { background: '#DBEAFE', color: '#1D4ED8' }, cancelado: { background: '#FEE2E2', color: '#B91C1C' } }
export const Estado = ({ value }) => <span className="est" style={ESTADO_COLOR[value]}>{value}</span>

// Actualizar estado de pedido (entregado) o cancelarlo (devuelve las unidades al inventario).
function CambioEstado({ auth, pedido, estado, close, onDone }) {
  const [motivo, setMotivo] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const cancelar = estado === 'cancelado'
  const submit = async e => {
    e.preventDefault(); setBusy(true); setError('')
    try { await api(`/pedidos/${pedido.id_pedido}/estado`, { method: 'PATCH', token: auth.token, body: { estado, ...(cancelar ? { motivo } : {}) } }); onDone() }
    catch (x) { setError(message(x)) } finally { setBusy(false) }
  }
  return <div className="scrim"><form className="modal w" onSubmit={submit}>
    <button type="button" className="x" onClick={close} aria-label="Cerrar">×</button>
    <h2>{cancelar ? 'Cancelar' : 'Marcar como entregado'} el pedido FS-{pedido.id_pedido}</h2>
    <p className="mute">{pedido.cliente} · {pedido.fecha_pedido} · {fmt(pedido.total)}</p>
    <fieldset disabled={busy}>
      {cancelar ? <><p className="note">Las unidades vendidas vuelven al inventario y queda registrado el movimiento. Esta acción no se puede deshacer.</p>
        <label htmlFor="motivo">Motivo de la cancelación</label><input id="motivo" required minLength={3} maxLength={150} autoFocus placeholder="Ej.: el cliente desistió de la compra" value={motivo} onChange={e => setMotivo(e.target.value)} /></>
        : <p>Confirma que el cliente ya recibió los productos. Un pedido entregado ya no se puede cancelar.</p>}
      <p className="err" role="alert">{error}</p>
      <div className="subform-acts"><button type="button" className="link" onClick={close}>Volver</button>
        <button className="yel">{busy ? 'Guardando…' : cancelar ? 'Cancelar pedido' : 'Confirmar entrega'}</button></div>
    </fieldset>
  </form></div>
}

export function Orders({ auth, onReceipt, version = 0, onChange }) {
  const [rows, setRows] = useState([])
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(true)
  const [cambio, setCambio] = useState(null)  // { pedido, estado }
  const load = () => { setLoading(true); setError(''); api('/pedidos', { token: auth.token }).then(setRows).catch(x => setError(message(x))).finally(() => setLoading(false)) }
  useEffect(load, [auth.token, version])
  const staff = auth.rol !== 'cliente'
  const acciones = r => r.estado !== 'confirmado' ? null : <>
    {staff && <button onClick={() => setCambio({ pedido: r, estado: 'entregado' })}>Marcar entregado</button>}
    {(staff || !r.id_empleado) && <button className="del" onClick={() => setCambio({ pedido: r, estado: 'cancelado' })}>Cancelar</button>}
  </>
  return <section className="panel orders"><div className="section-head"><h2>{auth.rol === 'cliente' ? 'Mis compras y comprobantes' : 'Ventas registradas'}</h2><button className="link" onClick={load}>Actualizar ventas</button></div>
    <p className="err" role="alert">{error}</p>{loading ? <p>Cargando ventas…</p> : <div className="table-scroll"><table><thead><tr><th>Venta</th><th>Fecha</th><th>Cliente</th><th>Empleado</th><th>Total</th><th>Estado</th><th>Comprobante</th><th>Acciones</th></tr></thead><tbody>
      {rows.map(r => <tr key={r.id_pedido}><td>FS-{r.id_pedido}</td><td>{r.fecha_pedido}</td><td>{r.cliente}</td><td>{r.empleado || 'Compra del cliente'}</td><td>{fmt(r.total)}</td><td><Estado value={r.estado} /></td><td><button className="link" onClick={() => onReceipt(r.id_pedido)}>Ver comprobante</button></td><td className="acts">{acciones(r)}</td></tr>)}
    </tbody></table>{!rows.length && !error && <p className="mute">Todavía no hay ventas registradas.</p>}</div>}
    {cambio && <CambioEstado auth={auth} pedido={cambio.pedido} estado={cambio.estado} close={() => setCambio(null)} onDone={() => { setCambio(null); load(); onChange?.() }} />}
  </section>
}

export function Seller({ auth, meds, reload, onReceipt }) {
  const [client, setClient] = useState(null)
  const [search, setSearch] = useState({ tipo_documento: 'CC', documento: '' })
  const [draft, setDraft] = useState(emptyClient)
  const [creating, setCreating] = useState(false)
  const [clientBusy, setClientBusy] = useState(false)
  const [error, setError] = useState('')
  const [cart, setCart] = useState({})
  const [rx, setRx] = useState({})
  const [payment, setPayment] = useState('Efectivo')
  const [version, setVersion] = useState(0)
  const sale = useSale(auth, o => { setCart({}); setRx({}); setVersion(v => v + 1); reload(); onReceipt(o.id_pedido) }, reload)
  const ids = Object.keys(cart)
  const find = async e => {
    e.preventDefault(); setError(''); setClient(null); setCreating(false); setClientBusy(true)
    try {
      const found = await api('/clientes?' + new URLSearchParams(search), { token: auth.token })
      if (found.length) setClient(found[0])
      else { setDraft({ ...emptyClient, ...search }); setCreating(true) }
    } catch (x) { setError(message(x)) }
    finally { setClientBusy(false) }
  }
  const register = async e => {
    e.preventDefault(); if (clientBusy) return; setClientBusy(true); setError('')
    try { setClient(await api('/clientes', { method: 'POST', token: auth.token, body: draft })); setCreating(false) }
    catch (x) { setError(message(x)) }
    finally { setClientBusy(false) }
  }
  const setQuantity = (id, raw) => {
    const quantity = Number(raw)
    setCart(c => { const next = { ...c }; quantity > 0 ? next[id] = quantity : delete next[id]; return next })
  }
  const formulaField = (id, key, label, type = 'text') => <div key={key}><label htmlFor={`rx-${id}-${key}`}>{label}</label><input id={`rx-${id}-${key}`} type={type} required maxLength={key === 'medico' ? 100 : 50} value={rx[id]?.[key] || ''} onChange={e => setRx(r => ({ ...r, [id]: { ...r[id], [key]: e.target.value } }))} /></div>
  return <>
    <section className="banner"><div><h1>Ventas y clientes · FarmaSalud</h1><p>{auth.correo} · Atención presencial con existencias reales.</p></div><button className="yel" onClick={reload}>Actualizar existencias</button></section>
    <div className="two2 pos">
      <section className="panel"><h2>1. Buscar o registrar cliente</h2>
        <fieldset disabled={sale.busy || clientBusy}><form onSubmit={find} className="two search-client"><div><label htmlFor="search-type">Tipo</label><select id="search-type" value={search.tipo_documento} onChange={e => setSearch({ ...search, tipo_documento: e.target.value })}>{['CC', 'CE', 'TI', 'PAS', 'NIT'].map(t => <option key={t}>{t}</option>)}</select></div><div><label htmlFor="search-document">Documento del cliente</label><input id="search-document" required maxLength={20} value={search.documento} onChange={e => setSearch({ ...search, documento: e.target.value })} /></div><button className="yel">Buscar cliente</button></form>
        {creating && <form onSubmit={register}><p className="note">No existe ese documento. Registra los datos del nuevo cliente.</p><ClientFields value={draft} onChange={setDraft} /><button className="yel">Guardar cliente</button></form>}</fieldset>
        {client && <div className="note"><b>Cliente seleccionado: {client.nombre} {client.apellido}</b><p>{client.tipo_documento} {client.documento} · {client.correo}</p></div>}
        <p className="err" role="alert">{error}</p>
      </section>
      <section className="panel"><h2>2. Seleccionar medicamentos</h2><p className="mute">Los productos ya existen en la base de datos.</p>
        <fieldset disabled={sale.busy}><div className="table-scroll"><table><thead><tr><th>Producto</th><th>Disponible</th><th>Precio</th><th>Cantidad</th></tr></thead><tbody>{meds.map(m => <tr key={m.id_medicamento}><td>{m.nombre}{m.requiere_formula && <small className="rx">Fórmula requerida</small>}</td><td>{m.stock}</td><td>{fmt(m.precio)}</td><td><input className="quantity-input" aria-label={'Cantidad ' + m.nombre} type="number" min="0" max={Math.max(0, m.stock)} step="1" value={cart[m.id_medicamento] || 0} onChange={e => setQuantity(m.id_medicamento, e.target.value)} /></td></tr>)}</tbody></table></div></fieldset>
      </section>
    </div>
    <form className="panel orders" onSubmit={e => { e.preventDefault(); sale.submit({ id_cliente: client.id_cliente, metodo_pago: payment, items: ids.map(id => ({ id_medicamento: +id, cantidad: cart[id], ...(meds.find(m => m.id_medicamento === +id)?.requiere_formula ? rx[id] || {} : {}) })) }) }}>
      <h2>3. Confirmar venta</h2><fieldset disabled={sale.busy}>
        {ids.filter(id => meds.find(m => m.id_medicamento === +id)?.requiere_formula).map(id => <div className="note" key={id}><b>Verificación de fórmula · {meds.find(m => m.id_medicamento === +id).nombre}</b><div className="two">{formulaField(id, 'numero_formula', 'Número de fórmula')}{formulaField(id, 'medico', 'Médico')}{formulaField(id, 'fecha_emision', 'Fecha de emisión', 'date')}{formulaField(id, 'fecha_vence', 'Fecha de vencimiento', 'date')}</div><label className="chk"><input required type="checkbox" checked={rx[id]?.formula_verificada || false} onChange={e => setRx(r => ({ ...r, [id]: { ...r[id], formula_verificada: e.target.checked } }))} />He revisado la fórmula y autorizo esta venta.</label></div>)}
        <Payment value={payment} onChange={setPayment} /><div className="totbox"><span>Total de productos</span><b>{fmt(ids.reduce((sum, id) => sum + Number(meds.find(m => m.id_medicamento === +id)?.precio || 0) * cart[id], 0))}</b></div>
        <p className="err" role="alert">{sale.error}</p><button className="yel" disabled={!client || !ids.length || sale.busy || clientBusy}>{sale.busy ? 'Confirmando…' : 'Confirmar venta y generar comprobante'}</button>
      </fieldset>
    </form>
    <Orders auth={auth} version={version} onReceipt={onReceipt} onChange={reload} />
  </>
}

export function Receipt({ id, auth, close }) {
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  // Se vuelve a leer lo persistido; no se arma la factura a partir del carrito.
  const load = () => { setError(''); api(`/pedidos/${id}/comprobante`, { token: auth.token }).then(setData).catch(x => setError(message(x))) }
  useEffect(load, [id, auth.token])
  return <div className="scrim receipt-overlay"><article className="modal w receipt" role="dialog" aria-modal="true" aria-label="Comprobante de venta">
    <div className="no-print section-head"><button className="link" onClick={close}>Cerrar comprobante</button>{data && <button className="yel" onClick={() => window.print()}>Imprimir / Guardar PDF</button>}</div>
    {error && <p className="err">{error} <button onClick={load}>Reintentar consulta</button></p>}
    {!data ? <p>Cargando comprobante desde PostgreSQL…</p> : <>
      <h1>FarmaSalud</h1><h2>Comprobante de venta {data.numero}</h2><p>Fecha: {data.fecha} · Estado: <Estado value={data.estado} /></p>
      {data.estado === 'cancelado' && <p className="note">Pedido cancelado{data.actualizado_por ? ` por ${data.actualizado_por}` : ''}. Motivo: {data.motivo_cancelacion}. Las unidades volvieron al inventario.</p>}
      <div className="sum"><p><b>Cliente:</b> {data.cliente.nombre}</p><p>{data.cliente.tipo_documento} {data.cliente.documento}</p><p>{data.cliente.correo} · {data.cliente.celular}</p><p><b>Empleado:</b> {data.empleado || 'Compra del cliente'}</p><p><b>Dirección:</b> {data.direccion}</p><p><b>Método de pago:</b> {data.metodo_pago}</p></div>
      <div className="table-scroll"><table><thead><tr><th>Producto</th><th>Cantidad</th><th>Precio unitario</th><th>Subtotal</th></tr></thead><tbody>{data.items.map(i => <tr key={i.id_medicamento}><td>{i.nombre}</td><td>{i.cantidad}</td><td>{fmt(i.precio)}</td><td>{fmt(i.subtotal)}</td></tr>)}</tbody></table></div>
      <div className="totbox"><b>Total COP</b><b>{fmt(data.total)}</b></div><p className="mute">Comprobante académico. No constituye factura electrónica ni confirmación de pago electrónico.</p>
    </>}
  </article></div>
}
