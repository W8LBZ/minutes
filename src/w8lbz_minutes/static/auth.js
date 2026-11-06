// Passkey (WebAuthn) helpers: convert between the server's JSON options and the browser API.
const b64u = {
  toBuf: (s) => Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((s.length + 3) % 4)), (c) => c.charCodeAt(0)).buffer,
  fromBuf: (b) => btoa(String.fromCharCode(...new Uint8Array(b))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""),
};
const passkeysSupported = () => !!window.PublicKeyCredential && window.isSecureContext;

function credToJSON(c) {
  const r = c.response, out = { id: c.id, rawId: b64u.fromBuf(c.rawId), type: c.type,
    clientExtensionResults: c.getClientExtensionResults ? c.getClientExtensionResults() : {}, response: {} };
  if (c.authenticatorAttachment) out.authenticatorAttachment = c.authenticatorAttachment;
  for (const k of ["clientDataJSON", "attestationObject", "authenticatorData", "signature", "userHandle"])
    if (r[k]) out.response[k] = b64u.fromBuf(r[k]);
  if (r.getTransports) out.response.transports = r.getTransports();
  return out;
}

async function post(url, body) {
  const r = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.detail || `Request failed (${r.status})`);
  return data;
}

async function passkeySignIn(next) {
  const o = await post("/auth/passkey/login/options");
  o.challenge = b64u.toBuf(o.challenge);
  (o.allowCredentials || []).forEach((c) => (c.id = b64u.toBuf(c.id)));
  const cred = await navigator.credentials.get({ publicKey: o });
  return post("/auth/passkey/login/verify", { credential: credToJSON(cred), next });
}

async function passkeyRegister(label) {
  const o = await post("/auth/passkey/register/options");
  o.challenge = b64u.toBuf(o.challenge);
  o.user.id = b64u.toBuf(o.user.id);
  (o.excludeCredentials || []).forEach((c) => (c.id = b64u.toBuf(c.id)));
  const cred = await navigator.credentials.create({ publicKey: o });
  return post("/auth/passkey/register/verify", { credential: credToJSON(cred), label });
}
