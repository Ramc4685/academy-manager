/**
 * localStorage key for the app lock setting. Its own module so the root layout's
 * pre-paint script can read it without importing Firebase code.
 */
export const APP_LOCK_KEY = "am.biometricLock";

/**
 * Runs before first paint inside the app shell: hides the page while the lock is
 * on, so nothing shows before the lock screen loads (app/globals.css).
 */
export const APP_LOCK_BOOT_SCRIPT = `try{if(localStorage.getItem(${JSON.stringify(APP_LOCK_KEY)})==="1"&&window.Capacitor&&window.Capacitor.isNativePlatform())document.documentElement.setAttribute("data-app-lock","")}catch(e){}`;
