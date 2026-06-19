const LOCAL_BFF_API_ORIGIN = "http://127.0.0.1:8001";
const PRODUCTION_BFF_API_ORIGIN = "https://api.academy.courtmastr.com";

export function resolveBffApiOrigin(env: {
  BFF_API_ORIGIN?: string;
  NODE_ENV?: string;
}): string {
  if (env.BFF_API_ORIGIN) return env.BFF_API_ORIGIN;
  return env.NODE_ENV === "production" ? PRODUCTION_BFF_API_ORIGIN : LOCAL_BFF_API_ORIGIN;
}
