import { useEffect, useState } from 'react'
import { api } from './api'
import './styles.css'

const fmt = n => '$' + Number(n).toLocaleString('es-CO')
const TODOS = 'Todos los productos'
const ART = { 'Analgésicos': ['💊', '#BFDBFE', '#60A5FA'], 'Antibióticos': ['💊', '#FDE68A', '#F59E0B'], 'Vitaminas': ['FarmaSalud', '#6D28D9', '#5B21B6'], 'Antihistamínicos': ['🤧', '#DDD6FE', '#A78BFA'],
  'Pediatría': ['🍼', '#FBCFE8', '#F472B6'], 'Dermofarmacia': ['🧴', '#BBF7D0', '#34D399'], 'Digestivos': ['💧', '#FED7AA', '#FB923C'] }
const Art = ({ m, sm, children }) => {
  const a = ART[m.categoria] || ART['Analgésicos']
  return <div className={'art' + (sm ? ' sm' : '') + (a[0].length > 3 && !sm ? ' t' : '')} style={{ background: `linear-gradient(135deg,${a[1]},${a[2]})` }}>{sm ? a[0].slice(0, 2) : a[0]}{children}</div>
}

export default function App() {
  const [role, setRole] = useState('cliente')
  const [meds, setMeds] = useState([])
  const [q, setQ] = useState('')
  const [cat, setCat] = useState(TODOS)
  const [favs, setFavs] = useState([])
  const [onlyFav, setOnlyFav] = useState(false)
  const [cart, setCart] = useState({})
  const [formulas, setFormulas] = useState({})
  const [auth, setAuth] = useState(null)
  const [drawer, setDrawer] = useState(false)
  const [modal, setModal] = useState(null) // login | checkout | done
  const [toast, setToast] = useState('')
  const [order, setOrder] = useState(null)
  const [newMed, setNewMed] = useState(false)

  const say = t => { setToast(t); setTimeout(() => setToast(''), 2200) }
  const soon = () => say('Disponible en el Prototipo 2')
  const loadMeds = () => api('/medicamentos').then(setMeds).catch(() => say('No se pudo cargar el catálogo'))
  useEffect(() => { loadMeds() }, [])

  const cats = [TODOS, ...Array.from(new Set(meds.map(m => m.categoria)))]
  const med = id => meds.find(m => m.id_medicamento === +id)
  const ids = Object.keys(cart)
  const count = Object.values(cart).reduce((a, b) => a + b, 0)
  const total = ids.reduce((a, id) => a + Number(med(id)?.precio || 0) * cart[id], 0)
  const name = auth ? auth.correo.split('@')[0].replace(/^./, c => c.toUpperCase()) : 'Carlos'

  const change = (id, d) => {
    const m = med(id), n = (cart[id] || 0) + d
    if (n > m.stock) return say('No hay más unidades disponibles')
    setCart(c => { const x = { ...c }; n <= 0 ? delete x[id] : (x[id] = n); return x })
  }
  const pay = () => { if (!auth) { setDrawer(false); setModal('login'); return say('Inicia sesión para pagar') } setDrawer(false); setModal('checkout') }
  const toggleFav = id => setFavs(f => f.includes(id) ? f.filter(x => x !== id) : [...f, id])
  const list = meds.filter(m => (cat === TODOS || m.categoria === cat) && (!onlyFav || favs.includes(m.id_medicamento)) && m.nombre.toLowerCase().includes(q.toLowerCase()))
  const chipLabel = { cliente: 'Cliente', vendedor: 'Boticario / Vendedor', admin: 'Administrador' }[role]

  return (
    <>
      <header>
        <div className="logo"><i>🧪</i><div><b>Farma<span>Salud</span></b><small>DROGUERÍA DIGITAL</small></div></div>
        <input className="search" placeholder="Buscar medicamentos, vitaminas, cuidado personal..." aria-label="Buscar" value={q} onChange={e => { setQ(e.target.value); setRole('cliente') }} />
        <div className="seg">{[['cliente', 'Cliente'], ['vendedor', 'Vendedor'], ['admin', 'Admin']].map(([k, l]) => <button key={k} className={role === k ? 'on' : ''} onClick={() => setRole(k)}>{l}</button>)}</div>
        <button className="bag" aria-label="Carrito" onClick={() => setDrawer(true)}>🛍<b>{count}</b></button>
        {auth ? (
          <div className="user"><div className="av">{name.slice(0, 2).toUpperCase()}</div><div><b>{name}</b><span className="chip">{chipLabel}</span></div>
            <button className="out" aria-label="Cerrar sesión" onClick={() => { setAuth(null); say('Sesión cerrada') }}>⎋</button></div>
        ) : <button className="yel" onClick={() => setModal('login')}>Iniciar sesión</button>}
      </header>

      <div className="wrap">
        {role === 'cliente' && (
          <div className="lay">
            <aside className="side">
              <div className="menu"><b>Menú Principal</b><small>Navega por tus servicios</small></div>
              <button className={'nav' + (!onlyFav ? ' on' : '')} onClick={() => setOnlyFav(false)}>🏠 Inicio / Catálogo</button>
              <button className="nav" onClick={soon}>📄 Mis Recetas</button>
              <button className={'nav' + (onlyFav ? ' on' : '')} onClick={() => setOnlyFav(true)}>♡ Mis Favoritos{favs.length > 0 && <em>{favs.length}</em>}</button>
              <button className="nav" onClick={soon}>👤 Mi Perfil</button>
              <div className="promo"><span>ENVÍO GRATIS</span><b>En compras superiores a $50.000 COP</b><p>Aplica para toda la ciudad de Bucaramanga.</p></div>
            </aside>
            <main>
              <section className="hero">
                <div><span className="lbl">TU SALUD EN BUENAS MANOS</span><h1>Encuentra tus medicamentos con entrega prioritaria</h1>
                  <p>Sube tu fórmula médica o explora nuestro catálogo digital verificado.</p><button className="yel" onClick={soon}>⬆ Subir Fórmula Médica</button></div>
                <div className="pic">💊</div>
              </section>
              <div className="cats">{cats.map(c => <button key={c} className={cat === c ? 'on' : ''} onClick={() => setCat(c)}>{c}</button>)}</div>
              <div className="pgrid">
                {list.map(m => (
                  <article className="pc" key={m.id_medicamento}>
                    <Art m={m}>
                      {(m.etiqueta || m.requiere_formula) && <span className="lab">{m.etiqueta || 'Requiere Receta'}{m.requiere_formula ? ' 📄' : ''}</span>}
                      <button className="fav" aria-label="Favorito" onClick={() => toggleFav(m.id_medicamento)}>{favs.includes(m.id_medicamento) ? '♥' : '♡'}</button>
                    </Art>
                    <span className="tag">{m.categoria.toUpperCase()}</span>
                    <h3>{m.nombre}</h3><p>Stock disponible: {m.stock} unids.</p>
                    <div className="foot"><div><small>Precio</small><b>{fmt(m.precio)} COP</b></div>
                      <button className="yel" disabled={m.stock === 0} onClick={() => { change(m.id_medicamento, 1); say('Agregado al carrito') }}>{m.stock === 0 ? 'Agotado' : '+ Añadir'}</button></div>
                  </article>
                ))}
              </div>
              {!list.length && <p className="mute">Ningún producto coincide con tu búsqueda.</p>}
            </main>
          </div>
        )}
        {role === 'vendedor' && <Seller name={name} soon={soon} />}
        {role === 'admin' && <>
          <Admin meds={meds} onNew={() => { setNewMed(true); setTimeout(() => document.getElementById('inv')?.scrollIntoView({ behavior: 'smooth' }), 50) }} />
          <Inventory meds={meds} auth={auth} say={say} reload={loadMeds} open={newMed} setOpen={setNewMed} login={() => setModal('login')} /></>}
      </div>

      {drawer && (
        <div className="scrim r" onClick={() => setDrawer(false)}>
          <aside className="drawer" onClick={e => e.stopPropagation()} aria-label="Carrito">
            <div className="dh"><span>🛍 Tu Carrito FarmaSalud</span><button onClick={() => setDrawer(false)} aria-label="Cerrar">×</button></div>
            {ids.some(id => med(id).requiere_formula) && <div className="warnbar">⚠ Uno o más items en tu carrito requieren presentación de receta médica.</div>}
            <div className="items">
              {ids.map(id => { const m = med(id); return (
                <div className="it" key={id}><Art m={m} sm />
                  <div className="i"><b>{m.nombre} {m.categoria.split(' ')[0]}</b><span className="mono">$ {Number(m.precio).toLocaleString('es-CO')}</span>
                    {m.requiere_formula && <div><span className="rx">Receta requerida</span></div>}</div>
                  <div className="qty"><button onClick={() => change(id, -1)} aria-label="Quitar uno">−</button>{cart[id]}<button onClick={() => change(id, 1)} aria-label="Agregar uno">+</button></div></div>) })}
              {!ids.length && <p className="mute">Tu carrito está vacío. Agrega productos desde el catálogo.</p>}
            </div>
            <div className="df">
              <div className="r"><span className="mute">Subtotal</span><b className="mono">$ {total.toLocaleString('es-CO')}</b></div>
              <div className="r"><span className="mute">Envío Domicilio</span><b style={{ color: 'var(--ok)' }}>{total >= 50000 || !total ? '¡GRATIS!' : '$ 5.000 al recibir'}</b></div>
              <div className="r tt"><span>Total Final</span><span className="mono">$ {total.toLocaleString('es-CO')}</span></div>
              <button className="yel full" disabled={!ids.length} onClick={pay}>Proceder al Pago →</button>
              <p className="mute" style={{ textAlign: 'center', fontSize: '.75rem', margin: '10px 0 0' }}>🛡 Compra 100% segura y garantizada por farmacéuticos</p>
            </div>
          </aside>
        </div>
      )}
      {modal === 'login' && <Login close={() => setModal(null)} onAuth={(a, t) => { setAuth(a); setModal(null); say(t); if (a.rol === 'admin') setRole('admin'); else if (a.rol === 'empleado') setRole('vendedor') }} />}
      {modal === 'checkout' && <Checkout cart={cart} ids={ids} med={med} total={total} auth={auth} formulas={formulas} setFormulas={setFormulas} close={() => setModal(null)}
        onDone={o => { setOrder(o); setCart({}); setFormulas({}); setModal('done'); loadMeds() }} />}
      {modal === 'done' && (
        <div className="scrim"><div className="modal ok">
          <div className="ck">✓</div><span className="ch">¡PEDIDO EXITOSO!</span>
          <h2>¡Gracias por tu compra!</h2><p>Orden registrada con número <b>#FS-{84900 + order.id_pedido}</b></p>
          <div className="sum"><div><span className="mute">Cliente:</span><b>{order.cliente}</b></div>
            <div><span className="mute">Tiempo de Entrega:</span><b style={{ color: 'var(--ok)' }}>30 - 45 Minutos</b></div>
            <div><span className="mute">Total Pagado:</span><b>{fmt(order.total)} COP</b></div></div>
          <button className="yel full" onClick={() => { setModal(null); setRole('cliente') }}>Volver a Inicio</button></div></div>
      )}
      {toast && <div className="toast" role="status">{toast}</div>}
    </>
  )
}

function Login({ close, onAuth }) {
  const [reg, setReg] = useState(false)
  const [f, setF] = useState({ correo: '', password: '' })
  const [err, setErr] = useState('')
  const submit = async e => {
    e.preventDefault(); setErr('')
    try { onAuth(await api(reg ? '/auth/register' : '/auth/login', { method: 'POST', body: f }), reg ? 'Cuenta creada' : 'Sesión iniciada') }
    catch (x) { setErr(x.message) }
  }
  return (
    <div className="scrim" onClick={close}><div className="modal" onClick={e => e.stopPropagation()}>
      <div className="mh"><button className="x" onClick={close} aria-label="Cerrar">✕</button><i>💊</i><h2>{reg ? 'Crear Cuenta' : 'Iniciar Sesión'}</h2><p>Accede a FarmaSalud Droguería Digital</p></div>
      <form className="mb" onSubmit={submit} noValidate>
        <label htmlFor="c">Correo Electrónico</label><input id="c" type="email" placeholder="usuario@mail.com" value={f.correo} onChange={e => setF({ ...f, correo: e.target.value })} />
        <label htmlFor="p">Contraseña</label><input id="p" type="password" placeholder="••••••••" value={f.password} onChange={e => setF({ ...f, password: e.target.value })} />
        <p className="err">{err}</p>
        <button className="yel full">{reg ? 'REGISTRARME' : 'INICIAR SESIÓN'}</button>
        <p className="mute" style={{ textAlign: 'center', margin: '16px 0 0', fontSize: '.85rem' }}>{reg ? '¿Ya tienes cuenta? ' : '¿No tienes cuenta? '}
          <button type="button" className="link" onClick={() => { setReg(!reg); setErr('') }}>{reg ? 'Iniciar sesión' : 'Registrarme'}</button></p>
      </form></div></div>
  )
}

function Checkout({ ids, cart, med, total, auth, formulas, setFormulas, close, onDone }) {
  const [f, setF] = useState({ nombre: '', tel: '', dir: '', td: 'CC', doc: '' })
  const [pago, setPago] = useState('Efectivo')
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const needF = ids.filter(id => med(id).requiere_formula)
  const set = k => e => setF({ ...f, [k]: e.target.value })
  const submit = async e => {
    e.preventDefault()
    if (Object.values(f).some(v => !v.trim())) return setErr('Completa todos los campos.')
    const miss = needF.find(id => !(formulas[id] || '').trim())
    if (miss) return setErr(`Ingresa el número de fórmula de ${med(miss).nombre}.`)
    const [nombre, ...rest] = f.nombre.trim().split(/\s+/)
    setBusy(true); setErr('')
    try {
      const o = await api('/pedidos', { method: 'POST', token: auth.token, body: {
        cliente: { tipo_documento: f.td, documento: f.doc, nombre, apellido: rest.join(' ') || '-', correo: auth.correo, celular: f.tel },
        direccion: f.dir, metodo_pago: pago,
        items: ids.map(id => ({ id_medicamento: +id, cantidad: cart[id], numero_formula: formulas[id] || null })) } })
      onDone({ ...o, cliente: f.nombre })
    } catch (x) { setErr(x.message); setBusy(false) }
  }
  return (
    <div className="scrim" onClick={close}><form className="modal w" onClick={e => e.stopPropagation()} onSubmit={submit} noValidate>
      <button type="button" className="x" onClick={close} aria-label="Cerrar">✕</button>
      <h2 style={{ margin: '0 0 6px', fontSize: '1.2rem' }}>💳 Finalizar Pedido Domicilio</h2><hr style={{ border: 0, borderTop: '1px solid var(--line)' }} />
      <div className="two"><div><label htmlFor="n">Nombre Completo</label><input id="n" value={f.nombre} onChange={set('nombre')} /></div>
        <div><label htmlFor="t">Teléfono Móvil</label><input id="t" inputMode="tel" placeholder="+57 315 000 0000" value={f.tel} onChange={set('tel')} /></div></div>
      <label htmlFor="d">Dirección de Entrega en Bucaramanga</label><input id="d" placeholder="Calle 36 # 28-14, Cabecera del Llano" value={f.dir} onChange={set('dir')} />
      <div className="two"><div><label htmlFor="td">Tipo de documento</label><select id="td" value={f.td} onChange={set('td')}>{['CC', 'CE', 'TI', 'PAS'].map(t => <option key={t}>{t}</option>)}</select></div>
        <div><label htmlFor="doc">Documento</label><input id="doc" inputMode="numeric" value={f.doc} onChange={set('doc')} /></div></div>
      {needF.length > 0 && <div className="note">{needF.map(id => <div key={id}><label htmlFor={'fm' + id}>Fórmula médica · {med(id).nombre}</label>
        <input id={'fm' + id} placeholder="N.º de fórmula" value={formulas[id] || ''} onChange={e => setFormulas({ ...formulas, [id]: e.target.value })} /></div>)}</div>}
      <label>Método de Pago</label>
      <div className="pays">{['Efectivo', 'Datafono', 'Nequi/PSE'].map(p => <label key={p} className={pago === p ? 'on' : ''}><input type="radio" name="pay" checked={pago === p} onChange={() => setPago(p)} />{p}</label>)}</div>
      <div className="totbox"><span className="mono" style={{ fontSize: '.85rem' }}>Total a Pagar:</span><b className="mono">$ {total.toLocaleString('es-CO')}</b></div>
      <p className="err">{err}</p>
      <button className="yel full" disabled={busy}>{busy ? 'Confirmando…' : 'Confirmar Pedido y Enviar Domicilio'}</button>
    </form></div>
  )
}

const Stat = ({ t, v, n, i, w }) => <div className="st"><div><small>{t}</small><b>{v}</b><em className={w ? 'w' : ''}>{n}</em></div><i>{i}</i></div>

function Seller({ name, soon }) {
  const rows = [['#FS-84918', 'Andrés Torres', '3 productos', '$42.500', 'Completada'], ['#FS-84917', 'Laura Sánchez', '1 producto', '$18.500', 'Completada'], ['#FS-84916', 'Julián Ramírez', '4 productos', '$89.000', 'En Proceso']]
  const cls = [['Andrés Torres', '12 compras • 312 *** 4920'], ['Laura Sánchez', '8 compras • 300 *** 1192'], ['Julián Ramírez', '15 compras • 315 *** 8830']]
  return (<>
    <section className="banner"><div><h1>¡Hola de nuevo, {name}! 👋</h1><p>Gestiona tus ventas y clientes de forma rápida y sencilla.</p></div><button className="yel" onClick={soon}>＋ Registrar Venta Rápida (POS)</button></section>
    <div className="stats"><Stat t="Ventas Hoy" v="$1.850.000 COP" n="↑ +32% vs ayer" i="$" /><Stat t="Clientes Atendidos" v="6 Atenciones" n="↑ +20% hoy" i="👥" />
      <Stat t="Total Vendido Hoy" v="$1.850.000" n="↑ +18% esta semana" i="📊" /><Stat t="Productos Consultados" v="42 Medicamentos" n="↑ +12% vs ayer" i="🧪" /></div>
    <div className="two2">
      <div className="panel"><h2>Últimas Ventas Registradas</h2><table><thead><tr>{['ORDEN #', 'CLIENTE', 'ITEMS', 'TOTAL COP', 'ESTADO', 'ACCIONES'].map(h => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>{rows.map(r => <tr key={r[0]}><td><a href="#o" onClick={e => e.preventDefault()}>{r[0]}</a></td><td><b>{r[1]}</b></td><td className="mute">{r[2]}</td><td><b>{r[3]} COP</b></td><td><span className="est">{r[4]}</span></td><td><a href="#v" onClick={e => { e.preventDefault(); soon() }}>Ver</a></td></tr>)}</tbody></table></div>
      <div className="panel"><h2>Buscar y Clientes Frecuentes</h2><input placeholder="Buscar por Nombre o Cédula..." aria-label="Buscar cliente" />
        {cls.map(c => <div className="cl" key={c[0]}><div className="av">{c[0][0]}</div><div><b>{c[0]}</b><small>{c[1]}</small></div><button className="link" onClick={soon}>Atender</button></div>)}</div>
    </div></>)
}

function Admin({ meds, onNew }) {
  const days = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'], v = [1.8, 2.1, 1.95, 2.45, 2.9, 3.2, 2.8]
  const pts = v.map((y, i) => `${50 + i * 100},${190 - (y - 1.8) / 1.4 * 150}`).join(' ')
  const leg = [['Analgésicos', '#6366F1'], ['Antibióticos', '#F59E0B'], ['Vitaminas', '#10B981'], ['Pediatría', '#3B82F6'], ['Dermofarmacia', '#EC4899']]
  return (<>
    <section className="banner a"><div><h1>Panel de Administración FarmaSalud</h1><p>Métricas de negocio, inventario farmacéutico y control de existencias</p></div><button className="yel" onClick={onNew}>＋ Nuevo Medicamento</button></section>
    <div className="stats"><Stat t="Ventas de Hoy" v="$2.450.000 COP" n="↗ +14.2% vs ayer" i="💰" /><Stat t="Pedidos Procesados" v="48 Despachos" n="✔ 100% a tiempo" i="📦" />
      <Stat t="Stock Crítico" v={`${meds.filter(m => m.stock <= 5).length} Medicamentos`} n="Requieren reabastecimiento" i="⚠" w /><Stat t="Clientes Atendidos" v="128 Pacientes" n="98% Satisfacción" i="👥" /></div>
    <div className="two2">
      <div className="panel"><h2>📈 Tendencia de Ventas de la Semana ($ COP)</h2>
        <svg viewBox="0 0 700 230" width="100%" role="img" aria-label="Ventas por día"><polyline points={`50,190 ${pts} 650,190`} fill="rgba(79,70,229,.1)" stroke="none" />
          <polyline points={pts} fill="none" stroke="#4F46E5" strokeWidth="3" />{v.map((y, i) => <g key={i}><circle cx={50 + i * 100} cy={190 - (y - 1.8) / 1.4 * 150} r="4" fill="#fff" stroke="#4F46E5" strokeWidth="2" />
            <text x={50 + i * 100} y="215" textAnchor="middle" fontSize="12" fill="#6B7280">{days[i]}</text></g>)}</svg></div>
      <div className="panel"><h2>◔ Ventas por Categoría</h2><div className="donut" role="img" aria-label="Ventas por categoría" /><div className="leg">{leg.map(l => <span key={l[0]} style={{ '--c': l[1] }}>{l[0]}</span>)}</div></div>
    </div></>)
}

function Inventory({ meds, auth, say, reload, open, setOpen, login }) {
  const empty = { nombre: '', mg: '', forma: '', id_categoria: '', id_laboratorio: '', precio: '', stock: '', requiere_formula: false }
  const [cat, setCat] = useState({ categorias: [], laboratorios: [] })
  const [f, setF] = useState(empty)
  useEffect(() => { api('/catalogos').then(setCat).catch(() => {}) }, [])
  if (!auth || auth.rol !== 'admin') return (
    <div className="panel" id="inv" style={{ marginTop: 20 }}><h2>📦 Inventario</h2>
      <p className="mute">Inicia sesión con una cuenta de administrador para agregar o quitar medicamentos.</p>
      {!auth && <button className="yel" onClick={login}>Iniciar sesión</button>}</div>)
  const tk = auth.token, set = k => e => setF({ ...f, [k]: e.target.value })
  const run = async (p, msg) => { try { await p; say(msg); reload() } catch (x) { say(x.message) } }
  const add = async e => {
    e.preventDefault()
    try {
      await api('/medicamentos', { method: 'POST', token: tk, body: { nombre: f.nombre, mg: f.mg ? +f.mg : null, forma: f.forma || null,
        id_categoria: +f.id_categoria, id_laboratorio: +f.id_laboratorio, precio: +f.precio, stock: +f.stock || 0, requiere_formula: f.requiere_formula } })
      say('Medicamento agregado'); setF(empty); setOpen(false); reload()
    } catch (x) { say(x.message) }
  }
  const adj = (m, d) => run(api(`/medicamentos/${m.id_medicamento}/stock`, { method: 'PATCH', token: tk, body: { delta: d, motivo: 'Ajuste desde el panel' } }), 'Stock actualizado')
  const del = m => window.confirm(`¿Quitar ${m.nombre} del catálogo?`) && run(api(`/medicamentos/${m.id_medicamento}`, { method: 'DELETE', token: tk }), 'Medicamento retirado')
  return (
    <div className="panel" id="inv" style={{ marginTop: 20 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}><h2 style={{ margin: 0 }}>📦 Inventario de medicamentos</h2>
        <button className="yel" onClick={() => setOpen(!open)}>{open ? 'Cancelar' : '＋ Nuevo Medicamento'}</button></div>
      {open && (
        <form onSubmit={add} className="fgrid">
          <div><label htmlFor="in">Nombre</label><input id="in" required value={f.nombre} onChange={set('nombre')} /></div>
          <div><label htmlFor="im">Dosis (mg)</label><input id="im" type="number" min="1" value={f.mg} onChange={set('mg')} /></div>
          <div><label htmlFor="if">Forma</label><input id="if" placeholder="Tableta, Cápsula…" value={f.forma} onChange={set('forma')} /></div>
          <div><label htmlFor="ic">Categoría</label><select id="ic" required value={f.id_categoria} onChange={set('id_categoria')}><option value="">Elegir…</option>{cat.categorias.map(c => <option key={c.id_categoria} value={c.id_categoria}>{c.nombre}</option>)}</select></div>
          <div><label htmlFor="il">Laboratorio</label><select id="il" required value={f.id_laboratorio} onChange={set('id_laboratorio')}><option value="">Elegir…</option>{cat.laboratorios.map(l => <option key={l.id_laboratorio} value={l.id_laboratorio}>{l.nombre}</option>)}</select></div>
          <div><label htmlFor="ip">Precio (COP)</label><input id="ip" type="number" min="0" required value={f.precio} onChange={set('precio')} /></div>
          <div><label htmlFor="is">Stock inicial</label><input id="is" type="number" min="0" value={f.stock} onChange={set('stock')} /></div>
          <label className="chk"><input type="checkbox" checked={f.requiere_formula} onChange={e => setF({ ...f, requiere_formula: e.target.checked })} /> Requiere fórmula médica</label>
          <button className="yel">Guardar medicamento</button>
        </form>)}
      <div style={{ overflowX: 'auto', marginTop: 14 }}><table><thead><tr>{['MEDICAMENTO', 'CATEGORÍA', 'LABORATORIO', 'PRECIO', 'STOCK', 'DISPONIBLE', 'ACCIONES'].map(h => <th key={h}>{h}</th>)}</tr></thead>
        <tbody>{meds.map(m => <tr key={m.id_medicamento}><td><b>{m.nombre}</b>{m.requiere_formula && ' 📄'}</td><td>{m.categoria}</td><td>{m.laboratorio}</td><td>{fmt(m.precio)}</td>
          <td>{m.stock_fisico}</td><td>{m.stock}</td>
          <td className="acts"><button onClick={() => adj(m, -1)}>−1</button><button onClick={() => adj(m, 10)}>+10</button><button className="del" onClick={() => del(m)}>Quitar</button></td></tr>)}</tbody></table></div>
    </div>)
}
