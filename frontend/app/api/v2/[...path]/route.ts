import type { NextRequest } from "next/server";
import { buildProxyHeaders, buildProxyResponseHeaders } from "@/lib/api/proxy-headers";

const BFF_API_ORIGIN = process.env.BFF_API_ORIGIN ?? "https://api.academy.courtmastr.com";

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
  const init: RequestInit = {
    method,
    headers: buildProxyHeaders(request.headers, request.nextUrl.protocol),
    redirect: "manual",
  };
  if (method !== "GET" && method !== "HEAD") {
    init.body = await request.arrayBuffer();
  }

  const upstream = await fetch(target, init);
  return new Response(upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: buildProxyResponseHeaders(upstream.headers),
  });
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
export const HEAD = proxy;
export const OPTIONS = proxy;
