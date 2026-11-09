import { useEffect, useState } from 'react'
import { api } from './api'
import './styles.css'
import { Checkout, Seller, Orders, Receipt } from './Sales'
import { Inventario } from './Inventario'
import { Informe } from './Informe'

const fmt = n => '$' + Number(n).toLocaleString('es-CO')
const TODOS = 'Todos los productos'
const ART = { 'Analgésicos': ['💊', '#BFDBFE', '#60A5FA'], 'Antibióticos': ['💊', '#FDE68A', '#F59E0B'], 'Vitaminas': ['FarmaSalud', '#6D28D9', '#5B21B6'], 'Antihistamínicos': ['🤧', '#DDD6FE', '#A78BFA'],
  'Pediatría': ['🍼', '#FBCFE8', '#F472B6'], 'Dermofarmacia': ['🧴', '#BBF7D0', '#34D399'], 'Digestivos': ['💧', '#FED7AA', '#FB923C'] }
const Art = ({ m, sm, children }) => {
  const a = ART[m.categoria] || ART['Analgésicos']
  return <div className={'art' + (sm ? ' sm' : '') + (a[0].length > 3 && !sm ? ' t' : '')} style={{ background: `linear-gradient(135deg,${a[1]},${a[2]})` }}>{sm ? a[0].slice(0, 2) : a[0]}{children}</div>
}

export default function App() {
  const [meds, setMeds] = useState([])
  const [q, setQ] = useState('')
  const [cat, setCat] = useState(TODOS)
  const [favs, setFavs] = useState([])
  const [onlyFav, setOnlyFav] = useState(false)
  const [cart, setCart] = useState({})
  const [auth, setAuth] = useState(null)
  const role = auth?.rol || 'cliente'
  const [history, setHistory] = useState(false)
  const [drawer, setDrawer] = useState(false)
  const [modal, setModal] = useState(null) // login | checkout
  const [toast, setToast] = useState('')
  const [order, setOrder] = useState(null)
  const [report, setReport] = useState(false)

  const say = t => { setToast(t); setTimeout(() => setToast(''), 2200) }
  const loadMeds = () => api('/medicamentos').then(setMeds).catch(() => say('No se pudo cargar el catálogo'))
  useEffect(() => { loadMeds() }, [])

  const cats = [TODOS, ...Array.from(new Set(meds.map(m => m.categoria)))]
  const med = id => meds.find(m => m.id_medicamento === +id)
  const ids = Object.keys(cart)
  const count = Object.values(cart).reduce((a, b) => a + b, 0)
  const total = ids.reduce((a, id) => a + Number(med(id)?.precio || 0) * cart[id], 0)
  const name = auth ? auth.correo.split('@')[0].replace(/^./, c => c.toUpperCase()) : 'Visitante'

  const change = (id, d) => {
    const m = med(id), n = (cart[id] || 0) + d
    if (!m) { say('Actualiza el catálogo antes de continuar'); return false }
    if (n > m.stock) { say('No hay más unidades disponibles'); return false }
    setCart(c => { const x = { ...c }; n <= 0 ? delete x[id] : (x[id] = n); return x })
  }
  const pay = () => { if (!auth) { setDrawer(false); setModal('login'); return say('Inicia sesión para pagar') } if (ids.some(id => med(id)?.requiere_formula)) return say('Los medicamentos con fórmula requieren atención del empleado'); setDrawer(false); setModal('checkout') }
  const toggleFav = id => setFavs(f => f.includes(id) ? f.filter(x => x !== id) : [...f, id])
  const list = meds.filter(m => (cat === TODOS || m.categoria === cat) && (!onlyFav || favs.includes(m.id_medicamento)) && m.nombre.toLowerCase().includes(q.toLowerCase()))
  const chipLabel = { cliente: 'Cliente', empleado: 'Boticario / Vendedor', admin: 'Administrador' }[role]

  return (
    <>
      <header>
        <div className="logo"><i>🧪</i><div><b>Farma<span>Salud</span></b><small>DROGUERÍA DIGITAL</small></div></div>
        <input className="search" placeholder="Buscar medicamentos, vitaminas, cuidado personal..." aria-label="Buscar" value={q} onChange={e => { setQ(e.target.value) }} />
        <div className="hright">
        {role === 'cliente' && <button className="bag" aria-label="Carrito" onClick={() => setDrawer(true)}>🛍<b>{count}</b></button>}
        {auth ? (
          <div className="user"><div className="av">{name.slice(0, 2).toUpperCase()}</div><div><b>{name}</b><span className="chip">{chipLabel}</span></div>
            <button className="out" aria-label="Cambiar contraseña" title="Cambiar contraseña" onClick={() => setModal('clave')}>🔑</button>
            <button className="out" aria-label="Cerrar sesión" title="Cerrar sesión" onClick={() => { setAuth(null); setCart({}); setOrder(null); setModal(null); setHistory(false); setReport(false); setDrawer(false); say('Sesión cerrada') }}>⎋</button></div>
        ) : <button className="yel" onClick={() => setModal('login')}>Iniciar sesión</button>}
        </div>
      </header>

      <div className="wrap">
        {role === 'cliente' && (
          <div className="lay">
            <aside className="side">
              <div className="menu"><b>Menú Principal</b><small>Navega por tus servicios</small></div>
              <button className={'nav' + (!onlyFav ? ' on' : '')} onClick={() => { setOnlyFav(false); setHistory(false) }}>🏠 Inicio / Catálogo</button>
              {auth && <button className="nav" onClick={() => setHistory(true)}>📄 Mis compras y comprobantes</button>}
              <button className={'nav' + (onlyFav ? ' on' : '')} onClick={() => { setOnlyFav(true); setHistory(false) }}>♡ Mis Favoritos{favs.length > 0 && <em>{favs.length}</em>}</button>

              <div className="promo"><span>VENTA ASISTIDA</span><b>¿Tu medicamento requiere fórmula médica?</b><p>Acércate a la droguería con tu fórmula: nuestro boticario la revisa y te atiende.</p></div>
            </aside>
            <main>
              {history && auth ? <Orders auth={auth} onReceipt={id => setOrder(id)} /> : <>
              <section className="hero">
                <div><span className="lbl">TU SALUD EN BUENAS MANOS</span><h1>Encuentra tus medicamentos con entrega prioritaria</h1>
                  <p>Consulta existencias y compra tus medicamentos. Los productos con fórmula requieren atención del empleado.</p><button className="yel" onClick={loadMeds}>Actualizar existencias</button></div>
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
                      <button className="yel" disabled={m.stock <= 0 || m.requiere_formula} onClick={() => { if (change(m.id_medicamento, 1) !== false) say('Agregado al carrito') }}>{m.requiere_formula ? 'Venta asistida' : m.stock <= 0 ? 'Agotado' : '+ Añadir'}</button></div>
                  </article>
                ))}
              </div>
              {!list.length && <p className="mute">Ningún producto coincide con tu búsqueda.</p>}
              </>}
            </main>
          </div>
        )}
        {role === 'empleado' && <Seller auth={auth} meds={meds} reload={loadMeds} onReceipt={setOrder} />}
        {role === 'admin' && <>
          <section className="banner"><div><h1>Administración FarmaSalud</h1><p>Gestión de inventario, ventas e informes.</p></div><button className="yel" onClick={() => setReport(true)}>Generar informe</button></section>
          <Inventario auth={auth} onChange={loadMeds} />
          <Orders auth={auth} onReceipt={setOrder} />
        </>}
      </div>

      {drawer && (
        <div className="scrim r" onClick={() => setDrawer(false)}>
          <aside className="drawer" onClick={e => e.stopPropagation()} aria-label="Carrito">
            <div className="dh"><span>🛍 Tu Carrito FarmaSalud</span><button onClick={() => setDrawer(false)} aria-label="Cerrar">×</button></div>
            {ids.some(id => med(id)?.requiere_formula) && <div className="warnbar">⚠ Uno o más items en tu carrito requieren presentación de receta médica.</div>}
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

              <div className="r tt"><span>Total Final</span><span className="mono">$ {total.toLocaleString('es-CO')}</span></div>
              <button className="yel full" disabled={!ids.length} onClick={pay}>Proceder al Pago →</button>
              <p className="mute" style={{ textAlign: 'center', fontSize: '.75rem', margin: '10px 0 0' }}>🛡 La disponibilidad se verifica nuevamente al confirmar</p>
            </div>
          </aside>
        </div>
      )}
      {modal === 'login' && <Login close={() => setModal(null)} onAuth={(a, t) => { setAuth(a); setModal(null); if (a.rol !== 'cliente') setCart({}); else if (ids.length) setDrawer(true); setHistory(false); say(t) }} />}
      {modal === 'clave' && auth && <CambiarClave auth={auth} close={() => setModal(null)} onDone={() => { setModal(null); say('Contraseña actualizada') }} />}
      {modal === 'checkout' && <Checkout cart={cart} ids={ids} med={med} auth={auth} reload={loadMeds} close={() => setModal(null)}
        onDone={o => { setOrder(o.id_pedido); setCart({}); setModal(null); loadMeds() }} />}
      {order !== null && <Receipt id={order} auth={auth} close={() => setOrder(null)} />}
      {report && role === 'admin' && <Informe auth={auth} close={() => setReport(false)} />}
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
        {reg && <p className="mute" style={{ fontSize: '.8rem', margin: '6px 0 0' }}>Mínimo 8 caracteres.</p>}
        <p className="err">{err}</p>
        <button className="yel full">{reg ? 'REGISTRARME' : 'INICIAR SESIÓN'}</button>
        <p className="mute" style={{ textAlign: 'center', margin: '16px 0 0', fontSize: '.85rem' }}>{reg ? '¿Ya tienes cuenta? ' : '¿No tienes cuenta? '}
          <button type="button" className="link" onClick={() => { setReg(!reg); setErr('') }}>{reg ? 'Iniciar sesión' : 'Registrarme'}</button></p>
      </form></div></div>
  )
}


function CambiarClave({ auth, close, onDone }) {
  const [f, setF] = useState({ actual: '', nueva: '', repetir: '' })
  const [err, setErr] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async e => {
    e.preventDefault(); setErr('')
    if (f.nueva !== f.repetir) return setErr('Las contraseñas nuevas no coinciden.')
    setBusy(true)
    try { await api('/auth/cambiar-clave', { method: 'POST', token: auth.token, body: { actual: f.actual, nueva: f.nueva } }); onDone() }
    catch (x) { setErr(x.message) } finally { setBusy(false) }
  }
  const field = (k, label) => <><label htmlFor={'k-' + k}>{label}</label><input id={'k-' + k} type="password" required minLength={k === 'actual' ? 1 : 8} maxLength={128} value={f[k]} onChange={e => setF({ ...f, [k]: e.target.value })} /></>
  return (
    <div className="scrim" onClick={close}><div className="modal" onClick={e => e.stopPropagation()}>
      <div className="mh"><button className="x" onClick={close} aria-label="Cerrar">✕</button><i>🔑</i><h2>Cambiar contraseña</h2><p>{auth.correo}</p></div>
      <form className="mb" onSubmit={submit}>
        <fieldset disabled={busy}>
          {field('actual', 'Contraseña actual')}{field('nueva', 'Contraseña nueva (mínimo 8 caracteres)')}{field('repetir', 'Repite la contraseña nueva')}
          <p className="err" role="alert">{err}</p>
          <button className="yel full">{busy ? 'Guardando…' : 'GUARDAR'}</button>
        </fieldset>
      </form></div></div>
  )
}
