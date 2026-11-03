/**
 * Google and Apple sign-in inside the iOS/Android app shell (see mobile/).
 *
 * Google refuses OAuth inside embedded webviews (`disallowed_useragent`), so in
 * the app the provider's native SDK signs the user in and we hand its ID token
 * to the web Firebase SDK. The browser path never reaches this module.
 *
 * Detection reads the `window.Capacitor` global the native shell injects, so
 * the web bundle never loads Capacitor code.
 */

import {
  GoogleAuthProvider,
  OAuthProvider,
  type AuthCredential,
} from "firebase/auth";

export type NativePlatform = "ios" | "android";
export type NativeProvider = "google" | "apple";

interface CapacitorGlobal {
  isNativePlatform?: () => boolean;
  getPlatform?: () => string;
  isPluginAvailable?: (name: string) => boolean;
}

function capacitor(): CapacitorGlobal | undefined {
  if (typeof window === "undefined") return undefined;
  return (window as unknown as { Capacitor?: CapacitorGlobal }).Capacitor;
}

export function nativePlatform(): NativePlatform | null {
  const cap = capacitor();
  if (!cap?.isNativePlatform?.()) return null;
  const platform = cap.getPlatform?.();
  return platform === "ios" || platform === "android" ? platform : null;
}

/**
 * True only inside the app shell when that build ships the named native
 * plugin. Older app builds without it keep the web behaviour instead of failing.
 */
export function hasNativePlugin(name: string): boolean {
  return nativePlatform() !== null && capacitor()?.isPluginAvailable?.(name) === true;
}

export function canUseNativeSignIn(): boolean {
  return hasNativePlugin("FirebaseAuthentication");
}

/** Sign in with Apple is offered on iOS, where App Review requires it alongside Google. */
export function shouldOfferAppleSignIn(): boolean {
  return nativePlatform() === "ios" && canUseNativeSignIn();
}

interface NativeSignInResult {
  credential?: { idToken?: string; accessToken?: string; nonce?: string } | null;
}

export function toFirebaseCredential(
  provider: NativeProvider,
  result: NativeSignInResult
): AuthCredential {
  const idToken = result.credential?.idToken;
  if (!idToken) {
    throw new Error(
      `${provider === "google" ? "Google" : "Apple"} sign-in did not return a token. Please try again.`
    );
  }
  if (provider === "google") {
    return GoogleAuthProvider.credential(idToken, result.credential?.accessToken);
  }
  return new OAuthProvider("apple.com").credential({
    idToken,
    rawNonce: result.credential?.nonce,
  });
}

export async function nativeCredential(provider: NativeProvider): Promise<AuthCredential> {
  const { FirebaseAuthentication } = await import("@capacitor-firebase/authentication");
  // skipNativeAuth: the web SDK owns the session (cookies, BFF bridge); the
  // native SDK only collects the provider token.
  const result =
    provider === "google"
      ? await FirebaseAuthentication.signInWithGoogle({ skipNativeAuth: true })
      : await FirebaseAuthentication.signInWithApple({ skipNativeAuth: true });
  return toFirebaseCredential(provider, result);
}
