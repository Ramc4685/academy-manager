import type { NextRequest } from "next/server";

const BFF_API_ORIGIN = process.env.BFF_API_ORIGIN ?? "http://127.0.0.1:8001";

type RouteContext = {
  params: Promise<{
    path: string[];
  }>;
};

const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

function proxyHeaders(request: NextRequest): Headers {
  const headers = new Headers(request.headers);
  const host = request.headers.get("host");
  if (host && !headers.has("x-forwarded-host")) {
    headers.set("x-forwarded-host", host);
  }
  if (!headers.has("x-forwarded-proto")) {
    headers.set("x-forwarded-proto", request.nextUrl.protocol.replace(":", ""));
  }
  headers.delete("host");
  return headers;
}

function responseHeaders(upstream: Response): Headers {
  const headers = new Headers(upstream.headers);
  for (const header of HOP_BY_HOP_HEADERS) {
    headers.delete(header);
  }
  return headers;
}

async function proxy(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  const target = new URL(`/api/v2/${path.join("/")}`, BFF_API_ORIGIN);
  target.search = request.nextUrl.search;

  const method = request.method.toUpperCase();
  const init: RequestInit = {
    method,
    headers: proxyHeaders(request),
    redirect: "manual",
  };
  if (method !== "GET" && method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  const upstream = await fetch(target, init);
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders(upstream),
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
export const OPTIONS = proxy;
