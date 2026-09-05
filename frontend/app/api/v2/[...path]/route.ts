import type { NextRequest } from "next/server";
import {
  REQUEST_ID_HEADER,
  buildProxyHeaders,
  buildProxyResponseHeaders,
} from "@/lib/api/proxy-headers";
import { resolveBffApiOrigin } from "@/lib/api/proxy-origin";

const BFF_API_ORIGIN = resolveBffApiOrigin(process.env);

type RouteContext = {
  params: Promise<{
    path: string[];
  }>;
};

async function proxy(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  const target = new URL(`/api/v2/${path.join("/")}`, BFF_API_ORIGIN);
  target.search = request.nextUrl.search;

  const method = request.method.toUpperCase();
  const headers = buildProxyHeaders(request.headers, request.nextUrl.protocol);
  const init: RequestInit = {
    method,
    headers,
    redirect: "manual",
  };
  if (method !== "GET" && method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  const upstream = await fetch(target, init);
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: buildProxyResponseHeaders(upstream.headers, headers.get(REQUEST_ID_HEADER)),
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
export const OPTIONS = proxy;
