import { useRef, useState } from 'react'

// Gráficas del informe en SVG puro (sin librerías). Una sola serie por gráfica: un solo color,
// sin leyenda; el valor va escrito junto a cada barra y el detalle aparece al pasar el mouse.

const fmtCOP = n => '$' + Number(n).toLocaleString('es-CO', { maximumFractionDigits: 0 })
const corto = n => {
  const v = Number(n)
  if (v >= 1e6) return '$' + (v / 1e6).toLocaleString('es-CO', { maximumFractionDigits: 1 }) + ' M'
  if (v >= 1e3) return '$' + (v / 1e3).toLocaleString('es-CO', { maximumFractionDigits: 0 }) + ' mil'
  return fmtCOP(v)
}

// Tope "redondo" del eje para que las líneas guía caigan en números limpios.
function tope(max) {
  if (max <= 0) return 1
  const p = 10 ** Math.floor(Math.log10(max)), f = max / p
  return (f <= 1 ? 1 : f <= 2 ? 2 : f <= 5 ? 5 : 10) * p
}

function useTooltip() {
  const caja = useRef(null)
  const [tip, setTip] = useState(null)
  const mover = (e, contenido) => {
    const r = caja.current.getBoundingClientRect()
    setTip({ x: e.clientX - r.left, y: e.clientY - r.top, ancho: r.width, contenido })
  }
  const vista = tip && <div className="viz-tip" role="status"
    style={{ left: Math.min(tip.x + 14, tip.ancho - 190), top: tip.y + 14 }}>{tip.contenido}</div>
  return { caja, mover, salir: () => setTip(null), vista }
}

// Barras horizontales: comparar magnitudes entre pocas categorías con nombre largo.
export function BarrasH({ titulo, datos, valor, etiqueta, formato = v => v, detalle, alerta, linea, unidad = '' }) {
  const t = useTooltip()
  const max = tope(Math.max(...datos.map(valor), linea?.valor ?? 0))
  // Con línea de referencia se deja una franja arriba para su rótulo, así no tapa la primera barra.
  const fila = 30, izq = 170, der = 110, W = 640, top = linea ? 18 : 0, H = top + datos.length * fila + 24
  const x = v => izq + (W - izq - der) * (v / max)
  return <figure className="viz" ref={t.caja} onMouseLeave={t.salir}>
    <figcaption>{titulo}</figcaption>
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label={titulo}>
      {[0, 0.5, 1].map(f => <g key={f}>
        <line x1={x(max * f)} x2={x(max * f)} y1={0} y2={H - 20} className="viz-grid" />
        <text x={x(max * f)} y={H - 6} textAnchor="middle" className="viz-eje">{formato(max * f)}</text>
      </g>)}
      {datos.map((d, i) => {
        const y = top + i * fila, v = valor(d), mala = alerta?.(d)
        return <g key={i} onMouseMove={e => t.mover(e, detalle(d))}>
          <rect x={0} y={y} width={W} height={fila} fill="transparent" />{/* zona de hover más grande que la barra */}
          <text x={izq - 10} y={y + fila / 2 + 4} textAnchor="end" className="viz-cat">
            {etiqueta(d).length > 24 ? etiqueta(d).slice(0, 23) + '…' : etiqueta(d)}</text>
          <rect x={izq} y={y + 7} width={Math.max(x(v) - izq, v > 0 ? 3 : 0)} height={fila - 14} rx={4}
            className={mala ? 'viz-bar warn' : 'viz-bar'} />
          <text x={Math.max(x(v), linea ? x(linea.valor) : 0) + 6} y={y + fila / 2 + 4} className="viz-val">{formato(v)}{unidad}{mala ? ' · Stock bajo' : ''}</text>
        </g>
      })}
      {linea && <g>
        <line x1={x(linea.valor)} x2={x(linea.valor)} y1={top - 4} y2={H - 20} className="viz-ref" />
        <text x={x(linea.valor) + 4} y={11} className="viz-eje">{linea.texto}</text>
      </g>}
    </svg>
    {t.vista}
  </figure>
}

// Columnas por día: ventas a lo largo del periodo. Los días sin ventas cuentan como 0 para no deformar el tiempo.
export function VentasPorDia({ desde, hasta, filas }) {
  const t = useTooltip()
  const porFecha = Object.fromEntries(filas.map(f => [f.fecha, f]))
  const dias = []
  for (let d = new Date(desde + 'T00:00'); d <= new Date(hasta + 'T00:00'); d.setDate(d.getDate() + 1)) {
    const k = d.toLocaleDateString('en-CA')
    dias.push({ fecha: k, total: Number(porFecha[k]?.total ?? 0), pedidos: porFecha[k]?.pedidos ?? 0 })
  }
  const max = tope(Math.max(...dias.map(d => d.total)))
  const W = 640, H = 220, izq = 64, abajo = 26, arriba = 10
  const paso = (W - izq) / dias.length, ancho = Math.max(Math.min(paso - 2, 28), 1)
  const y = v => arriba + (H - arriba - abajo) * (1 - v / max)
  const cada = Math.ceil(dias.length / 6)  // ~6 fechas en el eje para que no se encimen
  const fecha = k => new Date(k + 'T00:00').toLocaleDateString('es-CO', { day: 'numeric', month: 'short' })
  return <figure className="viz" ref={t.caja} onMouseLeave={t.salir}>
    <figcaption>Ventas por día (total vendido)</figcaption>
    <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Ventas por día">
      {[0, 0.5, 1].map(f => <g key={f}>
        <line x1={izq} x2={W} y1={y(max * f)} y2={y(max * f)} className="viz-grid" />
        <text x={izq - 8} y={y(max * f) + 4} textAnchor="end" className="viz-eje">{corto(max * f)}</text>
      </g>)}
      {dias.map((d, i) => {
        const cx = izq + i * paso + paso / 2
        return <g key={d.fecha} onMouseMove={e => t.mover(e, <><b>{fecha(d.fecha)}</b><br />{fmtCOP(d.total)} · {d.pedidos} pedido{d.pedidos === 1 ? '' : 's'}</>)}>
          <rect x={izq + i * paso} y={arriba} width={paso} height={H - arriba - abajo} fill="transparent" />
          {d.total > 0 && <rect x={cx - ancho / 2} y={y(d.total)} width={ancho} height={y(0) - y(d.total)} rx={Math.min(4, ancho / 2)} className="viz-bar" />}
          {i % cada === 0 && <text x={cx} y={H - 8} textAnchor="middle" className="viz-eje">{fecha(d.fecha)}</text>}
        </g>
      })}
    </svg>
    {t.vista}
  </figure>
}

export { fmtCOP, corto }
