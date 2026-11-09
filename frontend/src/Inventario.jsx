import { useEffect, useState } from 'react'
import { api } from './api'

const fmt = n => '$' + Number(n).toLocaleString('es-CO')
const vacio = { id_laboratorio: '', id_categoria: '', nombre: '', mg: '', forma: '', requiere_formula: false, precio: '', stock_inicial: 0 }

// Caso de uso "Gestionar Inventario": alta, edición, ajuste de stock y retiro de medicamentos.
export function Inventario({ auth, onChange }) {
  const [rows, setRows] = useState([])
  const [labs, setLabs] = useState([])
  const [cats, setCats] = useState([])
  const [form, setForm] = useState(null)      // { id?, ...campos }
  const [ajuste, setAjuste] = useState(null)  // medicamento a ajustar
  const [movs, setMovs] = useState(null)      // { med, lista }
  const [error, setError] = useState('')
  const call = (path, opts = {}) => api(path, { ...opts, token: auth.token })

  const load = () => Promise.all([call('/inventario'), call('/laboratorios'), call('/categorias')])
    .then(([i, l, c]) => { setRows(i); setLabs(l); setCats(c); setError('') })
    .catch(x => setError(x.message))
  useEffect(() => { load() }, [auth.token])
  const done = () => { load(); onChange() }

  const estado = async m => {
    if (m.activo && !confirm(`¿Retirar ${m.nombre} del catálogo? Las ventas anteriores se conservan.`)) return
    try { await call(`/medicamentos/${m.id_medicamento}${m.activo ? '' : '/reactivar'}`, { method: m.activo ? 'DELETE' : 'POST' }); done() }
    catch (x) { setError(x.message) }
  }
  const verMovs = async m => { try { setMovs({ med: m, lista: await call(`/inventario/movimientos?id_medicamento=${m.id_medicamento}`) }) } catch (x) { setError(x.message) } }

  return <section className="panel table-scroll">
    <div className="section-head"><h2>Gestión de inventario</h2>
      <div><button className="link" onClick={load}>Actualizar</button> <button className="yel" onClick={() => setForm({ ...vacio })}>+ Nuevo medicamento</button></div></div>
    <p className="err" role="alert">{error}</p>
    <table><thead><tr><th>Medicamento</th><th>Laboratorio</th><th>Categoría</th><th>Precio</th><th>Stock físico</th><th>Reservado</th><th>Disponible</th><th>Estado</th><th>Acciones</th></tr></thead>
      <tbody>{rows.map(m => <tr key={m.id_medicamento} style={m.activo ? null : { opacity: .55 }}>
        <td><div className="med-cell"><div className="thumb">{m.imagen_url ? <img src={m.imagen_url} alt="" /> : '💊'}</div><div><b>{m.nombre}{m.mg ? ` ${m.mg}mg` : ''}</b><br /><small className="mute">{m.forma || '—'}{m.requiere_formula ? ' · Requiere fórmula' : ''}</small></div></div></td>
        <td>{m.laboratorio}</td><td>{m.categoria}</td><td>{fmt(m.precio)}</td>
        <td>{m.stock_fisico}</td><td>{m.reservado}</td><td>{m.disponible}</td>
        <td><span className="est" style={m.activo ? null : { background: '#FEE2E2', color: '#B91C1C' }}>{m.activo ? 'Activo' : 'Retirado'}</span></td>
        <td className="acts"><button onClick={() => setForm({ ...m, id: m.id_medicamento, mg: m.mg ?? '', forma: m.forma ?? '' })}>Editar</button>
          <button onClick={() => setAjuste(m)}>Ajustar stock</button>
          <button onClick={() => verMovs(m)}>Movimientos</button>
          <button className={m.activo ? 'del' : ''} onClick={() => estado(m)}>{m.activo ? 'Retirar' : 'Reactivar'}</button></td>
      </tr>)}</tbody></table>
    {form && <MedForm auth={auth} value={form} labs={labs} cats={cats} close={() => setForm(null)} reloadRefs={load} onSaved={() => { setForm(null); done() }} />}
    {ajuste && <StockForm auth={auth} med={ajuste} close={() => setAjuste(null)} onSaved={() => { setAjuste(null); done() }} />}
    {movs && <div className="scrim" onClick={() => setMovs(null)}><div className="modal w" onClick={e => e.stopPropagation()}>
      <button className="x" onClick={() => setMovs(null)} aria-label="Cerrar">×</button><h2>Movimientos · {movs.med.nombre}</h2>
      <div className="table-scroll"><table><thead><tr><th>Fecha</th><th>Tipo</th><th>Cantidad</th><th>Motivo</th><th>Usuario</th></tr></thead>
        <tbody>{movs.lista.map(x => <tr key={x.id_movimiento}><td>{new Date(x.fecha).toLocaleString('es-CO')}</td><td>{x.tipo}</td><td>{x.cantidad}</td><td>{x.motivo}</td><td>{x.usuario || '—'}</td></tr>)}</tbody></table></div>
      {!movs.lista.length && <p className="mute">Sin movimientos registrados.</p>}
    </div></div>}
  </section>
}

const TIPOS_FOTO = ['image/jpeg', 'image/png', 'image/webp']
const MAX_FOTO = 2 * 1024 * 1024

async function subirFoto(auth, id, file) {
  const r = await fetch(`/api/medicamentos/${id}/imagen`, { method: 'PUT', body: file,
    headers: { 'Content-Type': file.type, Authorization: `Bearer ${auth.token}` } })
  if (!r.ok) {
    const d = await r.json().catch(() => ({}))
    throw new Error(typeof d.detail === 'string' ? d.detail : 'No se pudo subir la foto.')
  }
}

// Alta de laboratorio o categoría dentro del mismo formulario (sin ventanas del navegador).
function NuevaReferencia({ auth, tipo, onCreated, onCancel }) {
  const lab = tipo === 'laboratorios'
  const [nombre, setNombre] = useState('')
  const [pais, setPais] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const agregar = async () => {
    if (!nombre.trim()) return setError(`Escribe el nombre ${lab ? 'del laboratorio' : 'de la categoría'}.`)
    setBusy(true); setError('')
    try {
      const body = { nombre: nombre.trim(), ...(lab && pais.trim() ? { pais: pais.trim() } : {}) }
      const r = await api('/' + tipo, { method: 'POST', token: auth.token, body })
      onCreated(lab ? r.id_laboratorio : r.id_categoria)
    } catch (x) { setError(x.message) } finally { setBusy(false) }
  }
  const enter = e => { if (e.key === 'Enter') { e.preventDefault(); agregar() } if (e.key === 'Escape') { e.preventDefault(); onCancel() } }
  return <div className="subform">
    <b>{lab ? 'Nuevo laboratorio' : 'Nueva categoría'}</b>
    <div className={lab ? 'two' : ''}>
      <div><label htmlFor="r-nombre">Nombre</label><input id="r-nombre" autoFocus maxLength={100} disabled={busy} value={nombre} onChange={e => setNombre(e.target.value)} onKeyDown={enter} /></div>
      {lab && <div><label htmlFor="r-pais">País (opcional)</label><input id="r-pais" maxLength={50} disabled={busy} value={pais} onChange={e => setPais(e.target.value)} onKeyDown={enter} /></div>}
    </div>
    {error && <p className="err" role="alert">{error}</p>}
    <div className="subform-acts"><button type="button" className="link" onClick={onCancel} disabled={busy}>Cancelar</button>
      <button type="button" className="yel" onClick={agregar} disabled={busy}>{busy ? 'Agregando…' : 'Agregar'}</button></div>
  </div>
}

function MedForm({ auth, value, labs, cats, close, onSaved, reloadRefs }) {
  const [f, setF] = useState(value)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [ref, setRef] = useState(null)          // 'laboratorios' | 'categorias' | null
  const [foto, setFoto] = useState(null)        // archivo nuevo elegido
  const [quitar, setQuitar] = useState(false)   // quitar la foto actual
  const [preview, setPreview] = useState(null)
  const nuevo = !f.id
  const set = (k, v) => setF(x => ({ ...x, [k]: v }))
  useEffect(() => {
    if (!foto) { setPreview(null); return }
    const url = URL.createObjectURL(foto); setPreview(url)
    return () => URL.revokeObjectURL(url)
  }, [foto])
  const fotoActual = preview || (!quitar && value.imagen_url) || null

  const elegirFoto = e => {
    const file = e.target.files[0]; e.target.value = ''
    if (!file) return
    if (!TIPOS_FOTO.includes(file.type)) return setError('La foto debe ser JPG, PNG o WebP.')
    if (file.size > MAX_FOTO) return setError('La foto no puede superar 2 MB.')
    setError(''); setFoto(file); setQuitar(false)
  }
  const creada = async (campo, id) => { await reloadRefs(); set(campo, String(id)); setRef(null) }

  const submit = async e => {
    e.preventDefault(); setBusy(true); setError('')
    const body = { id_laboratorio: +f.id_laboratorio, id_categoria: +f.id_categoria, nombre: f.nombre, mg: f.mg === '' ? null : +f.mg,
      forma: f.forma.trim() || null, requiere_formula: f.requiere_formula, precio: +f.precio, ...(nuevo ? { stock_inicial: +f.stock_inicial } : {}) }
    let id = f.id
    try {
      const med = await api(nuevo ? '/medicamentos' : `/medicamentos/${f.id}`, { method: nuevo ? 'POST' : 'PUT', token: auth.token, body })
      id = med.id_medicamento
      if (foto) await subirFoto(auth, id, foto)
      else if (quitar && value.imagen_url) await api(`/medicamentos/${id}/imagen`, { method: 'DELETE', token: auth.token })
      onSaved()
    } catch (x) {
      // Si el medicamento ya se guardó y solo falló la foto, el formulario pasa a modo edición.
      if (id && nuevo) { set('id', id); setError('El medicamento se guardó, pero la foto no: ' + x.message) }
      else setError(x.message)
    } finally { setBusy(false) }
  }

  return <div className="scrim"><form className="modal w" onSubmit={submit}>
    <button type="button" className="x" onClick={close} aria-label="Cerrar">×</button><h2>{nuevo ? 'Nuevo medicamento' : 'Editar medicamento'}</h2>
    <fieldset disabled={busy}>
      <div className="foto-row">
        <div className="foto-prev">{fotoActual ? <img src={fotoActual} alt="Foto del medicamento" /> : <span>📷</span>}</div>
        <div>
          <b>Foto del medicamento</b>
          <p className="mute">JPG, PNG o WebP · máximo 2 MB. Es opcional.</p>
          <label className="file-btn">{fotoActual ? 'Cambiar foto' : 'Elegir foto'}<input type="file" accept={TIPOS_FOTO.join(',')} onChange={elegirFoto} /></label>
          {fotoActual && <button type="button" className="link" onClick={() => { setFoto(null); setQuitar(true) }}>Quitar foto</button>}
        </div>
      </div>
      <label htmlFor="m-nombre">Nombre</label><input id="m-nombre" required maxLength={150} value={f.nombre} onChange={e => set('nombre', e.target.value)} />
      <div className="two">
        <div><label htmlFor="m-mg">Concentración (mg)</label><input id="m-mg" type="number" min="1" value={f.mg} onChange={e => set('mg', e.target.value)} /></div>
        <div><label htmlFor="m-forma">Forma</label><input id="m-forma" maxLength={50} placeholder="Tableta, Cápsula…" value={f.forma} onChange={e => set('forma', e.target.value)} /></div>
        <div><label htmlFor="m-lab">Laboratorio <button type="button" className="link" onClick={() => setRef('laboratorios')}>+ nuevo</button></label>
          <select id="m-lab" required value={f.id_laboratorio} onChange={e => set('id_laboratorio', e.target.value)}><option value="">Selecciona…</option>{labs.map(l => <option key={l.id_laboratorio} value={l.id_laboratorio}>{l.nombre}</option>)}</select></div>
        <div><label htmlFor="m-cat">Categoría <button type="button" className="link" onClick={() => setRef('categorias')}>+ nueva</button></label>
          <select id="m-cat" required value={f.id_categoria} onChange={e => set('id_categoria', e.target.value)}><option value="">Selecciona…</option>{cats.map(c => <option key={c.id_categoria} value={c.id_categoria}>{c.nombre}</option>)}</select></div>
      </div>
      {ref && <NuevaReferencia key={ref} auth={auth} tipo={ref} onCancel={() => setRef(null)}
        onCreated={id => creada(ref === 'laboratorios' ? 'id_laboratorio' : 'id_categoria', id)} />}
      <div className="two">
        <div><label htmlFor="m-precio">Precio (COP)</label><input id="m-precio" required type="number" min="0" step="0.01" value={f.precio} onChange={e => set('precio', e.target.value)} /></div>
        {nuevo && <div><label htmlFor="m-stock">Stock inicial</label><input id="m-stock" required type="number" min="0" step="1" value={f.stock_inicial} onChange={e => set('stock_inicial', e.target.value)} /></div>}
      </div>
      <label className="chk" style={{ marginTop: 14 }}><input type="checkbox" checked={f.requiere_formula} onChange={e => set('requiere_formula', e.target.checked)} />Requiere fórmula médica (venta asistida)</label>
      {!nuevo && <p className="mute">El stock se modifica con "Ajustar stock", para que quede registrado el movimiento.</p>}
      <p className="err" role="alert">{error}</p>
      <button className="yel full">{busy ? 'Guardando…' : 'Guardar'}</button>
    </fieldset>
  </form></div>
}

function StockForm({ auth, med, close, onSaved }) {
  const [tipo, setTipo] = useState('entrada')
  const [cantidad, setCantidad] = useState('')
  const [motivo, setMotivo] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submit = async e => {
    e.preventDefault(); setBusy(true); setError('')
    try { await api(`/medicamentos/${med.id_medicamento}/stock`, { method: 'PATCH', token: auth.token, body: { cantidad: (tipo === 'entrada' ? 1 : -1) * +cantidad, motivo } }); onSaved() }
    catch (x) { setError(x.message) } finally { setBusy(false) }
  }
  return <div className="scrim"><form className="modal w" onSubmit={submit}>
    <button type="button" className="x" onClick={close} aria-label="Cerrar">×</button><h2>Ajustar stock · {med.nombre}</h2>
    <p className="mute">Stock físico actual: {med.stock_fisico} · reservado: {med.reservado}</p>
    <fieldset disabled={busy}>
      <div className="two">
        <div><label htmlFor="s-tipo">Tipo</label><select id="s-tipo" value={tipo} onChange={e => setTipo(e.target.value)}><option value="entrada">Entrada (suma)</option><option value="ajuste">Salida / ajuste (resta)</option></select></div>
        <div><label htmlFor="s-cant">Cantidad</label><input id="s-cant" required type="number" min="1" step="1" value={cantidad} onChange={e => setCantidad(e.target.value)} /></div>
      </div>
      <label htmlFor="s-mot">Motivo</label><input id="s-mot" required minLength={3} maxLength={200} placeholder="Compra a proveedor, vencidos, conteo físico…" value={motivo} onChange={e => setMotivo(e.target.value)} />
      <p className="err" role="alert">{error}</p>
      <button className="yel full">{busy ? 'Guardando…' : 'Registrar ajuste'}</button>
    </fieldset>
  </form></div>
}
