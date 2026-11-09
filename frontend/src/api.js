// Cliente único para hablar con FastAPI (todas las rutas empiezan por /api)
export async function api(path, { method = 'GET', body, token } = {}) {
  const r = await fetch('/api' + path, {
    method,
    headers: { 'Content-Type': 'application/json', ...(token ? { Authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  })
  const data = await r.json().catch(() => ({}))
  if (!r.ok) {
    const detail = Array.isArray(data.detail)
      ? data.detail.map(x => `${x.loc.slice(1).join('.')}: ${x.msg}`).join('; ')
      : data.detail
    throw new Error(typeof detail === 'string' ? detail : 'Revisa los datos ingresados.')
  }
  return data
}
