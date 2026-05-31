export async function resolveApiAuthToken(
  explicitAuthToken: string | null | undefined,
  getAmbientToken: () => Promise<string | null>
): Promise<string | null> {
  if (explicitAuthToken !== undefined) {
    return explicitAuthToken;
  }
  return getAmbientToken();
}
