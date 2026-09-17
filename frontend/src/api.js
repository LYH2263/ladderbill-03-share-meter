async function request(path, options) {
  const r = await fetch(path, options)
  if (!r.ok) {
    let message = `${r.status} ${r.statusText}`
    try {
      const body = await r.json()
      if (typeof body.detail === 'string') message = body.detail
      else if (Array.isArray(body.detail)) message = body.detail.map((d) => d.msg).join('；')
    } catch {
      const text = await r.text().catch(() => '')
      if (text) message = text
    }
    const err = new Error(message)
    err.status = r.status
    throw err
  }
  return r.json()
}

export function getJSON(path) {
  return request(path)
}

export function postJSON(path, body) {
  return request(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}

export function putJSON(path, body) {
  return request(path, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
}
