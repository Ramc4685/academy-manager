/**
 * Cloudflare Worker — academy-manager edge router.
 *
 * Routes production traffic to the maintained stack:
 *   1. API paths go to the FastAPI origin.
 *   2. All browser paths go to the Next.js frontend origin.
 *
 * Bind these env vars in `wrangler.toml`:
 *   API_ORIGIN     e.g. https://courtmastr-academy-api.fly.dev
 *   WEB_ORIGIN     e.g. https://academy-next.courtmastr.com
 */

type Env = {
  API_ORIGIN: string;
  WEB_ORIGIN: string;
};

type Decision = { kind: "proxy"; origin: string };

function decide(url: URL, env: Env): Decision {
  const path = url.pathname;

  if (path === "/api" || path.startsWith("/api/")) {
    return { kind: "proxy", origin: env.API_ORIGIN };
  }

  return { kind: "proxy", origin: env.WEB_ORIGIN };
}

async function proxy(request: Request, origin: string): Promise<Response> {
  const url = new URL(request.url);
  const target = new URL(url.pathname + url.search, origin);
  const init: RequestInit = {
    method: request.method,
    headers: request.headers,
    redirect: "manual",
  };
  if (request.method !== "GET" && request.method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }
  // Forward trace headers for observability.
  return fetch(target.toString(), init);
}

export default {
  async fetch(request: Request, env: Env): Promise<Response> {
    const url = new URL(request.url);
    const decision = decide(url, env);
    switch (decision.kind) {
      case "proxy":
        return proxy(request, decision.origin);
    }
  },
};

// Exported for unit tests.
export { decide };
export type { Env, Decision };
