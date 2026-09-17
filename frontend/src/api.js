async function handle(r) {
  const text = await r.text()
  if (!r.ok) {
    let msg = text
    try {
      const j = JSON.parse(text)
      msg = j.detail ?? text
    } catch { /* 非 JSON 错误体，原样展示 */ }
    throw new Error(typeof msg === 'string' ? msg : JSON.stringify(msg))
  }
  return text ? JSON.parse(text) : null
}
async function send(method, path, body) {
  const r = await fetch(path, { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) })
  return handle(r)
}
export async function getJSON(path) {
  return handle(await fetch(path))
}
export function postJSON(path, body) {
  return send('POST', path, body)
}
export function putJSON(path, body) {
  return send('PUT', path, body)
}
