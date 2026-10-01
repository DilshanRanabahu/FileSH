// Talking to the FileSh server.

export class ApiError extends Error {
  constructor(status, message, data = {}) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

export async function api(url, options = {}) {
  let response;
  try {
    response = await fetch(url, { credentials: "same-origin", ...options });
  } catch {
    throw new ApiError(0, "Can't reach your PC");
  }
  if (!response.ok) {
    let data = {};
    try {
      data = await response.json();
    } catch {
      // Not JSON.
    }
    throw new ApiError(response.status, data.error || `Error ${response.status}`, data);
  }
  return response;
}

export async function getJson(url) {
  return (await api(url)).json();
}

export async function sendJson(url, method = "POST", body = {}) {
  const response = await api(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return response.json();
}
