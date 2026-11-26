const BASE = "https://api.jikan.moe/v4";

// A Jikan pede no máximo cerca de 3 requisições por segundo.
const MIN_GAP_MS = 400;

let chain = Promise.resolve();
let lastStart = 0;

function delay(ms) {
  return new Promise((resolve) => {
    setTimeout(resolve, ms);
  });
}

export function enqueue(task) {
  const run = chain.then(async () => {
    const wait = MIN_GAP_MS - (Date.now() - lastStart);
    if (wait > 0) await delay(wait);
    lastStart = Date.now();
    return task();
  });
  chain = run.then(
    () => undefined,
    () => undefined,
  );
  return run;
}

export function timeoutSignal(ms) {
  if (typeof AbortSignal.timeout === "function") return AbortSignal.timeout(ms);
  const controller = new AbortController();
  setTimeout(() => controller.abort(new DOMException("timeout", "TimeoutError")), ms);
  return controller.signal;
}

export function combineSignals(signals) {
  const active = signals.filter(Boolean);
  if (typeof AbortSignal.any === "function") return AbortSignal.any(active);
  const controller = new AbortController();
  for (const signal of active) {
    if (signal.aborted) {
      controller.abort(signal.reason);
      return controller.signal;
    }
    signal.addEventListener("abort", () => controller.abort(signal.reason), { once: true });
  }
  return controller.signal;
}

function throwIfAborted(signal) {
  if (!signal?.aborted) return;
  if (signal.reason instanceof Error) throw signal.reason;
  throw new DOMException("aborted", "AbortError");
}

export function buildSearchUrl(type, { q, genre, status }) {
  const params = new URLSearchParams();
  params.set("sfw", "true");
  params.set("limit", "24");
  const query = (q || "").trim();
  if (query) {
    params.set("q", query);
  } else {
    params.set("order_by", "popularity");
    params.set("sort", "asc");
  }
  if (genre) params.set("genres", genre);
  if (status) params.set("status", status);
  return `${BASE}/${type}?${params.toString()}`;
}

export function buildGenresUrl(type) {
  const params = new URLSearchParams();
  params.set("filter", "genres");
  return `${BASE}/genres/${type}?${params.toString()}`;
}

export async function fetchJson(url, signal) {
  throwIfAborted(signal);
  let response;
  try {
    response = await fetch(url, {
      signal,
      headers: { Accept: "application/json" },
    });
  } catch (error) {
    if (error?.name === "AbortError" || error?.name === "TimeoutError") throw error;
    const failure = new Error("Não foi possível conectar ao serviço de dados.");
    failure.kind = "network";
    throw failure;
  }

  throwIfAborted(signal);

  if (!response.ok) {
    const failure = new Error(
      response.status === 429
        ? "O serviço limitou as consultas. Espere um instante e tente de novo."
        : `O serviço respondeu com erro (HTTP ${response.status}).`,
    );
    failure.kind = "http";
    failure.status = response.status;
    throw failure;
  }

  try {
    return await response.json();
  } catch {
    const failure = new Error("A resposta do serviço veio em um formato inválido.");
    failure.kind = "parse";
    throw failure;
  }
}
