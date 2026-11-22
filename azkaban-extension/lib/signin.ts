// Sign-in pages the extension must never touch.
//
// Google (and other identity providers) refuse to log you in when page APIs look tampered
// with: "Couldn't sign you in - this browser or app may not be secure". The MAIN-world probe
// wraps fetch, XHR, canvas and navigator, which is exactly what that check detects. So these
// pages get no content scripts at all (and nobody's password is ever near our input watcher),
// and their domains get a DNR allow rule that outranks every Patronus block and cookie rule.

/** Content-script exclude patterns (Chrome match-pattern syntax). */
export const SIGNIN_EXCLUDE_MATCHES = [
  "*://accounts.google.com/*",
  "*://*.accounts.google.com/*",
  "*://accounts.youtube.com/*",
  "*://myaccount.google.com/*",
  "*://gds.google.com/*",
  "*://login.microsoftonline.com/*",
  "*://login.live.com/*",
  "*://account.live.com/*",
  "*://appleid.apple.com/*",
  "*://idmsa.apple.com/*",
  "*://github.com/login*",
  "*://github.com/session*",
  "*://login.yahoo.com/*",
];

/** Domains (and their subdomains) a sign-in flow needs to load. Never blocked, never stripped. */
export const SIGNIN_ALLOW_DOMAINS = [
  "accounts.google.com",
  "accounts.youtube.com",
  "myaccount.google.com",
  "apis.google.com",
  "oauth2.googleapis.com",
  "www.googleapis.com",
  "ssl.gstatic.com",
  "www.gstatic.com",
  "fonts.gstatic.com",
  "play.google.com",
  "login.microsoftonline.com",
  "login.live.com",
  "appleid.apple.com",
  "idmsa.apple.com",
  "login.yahoo.com",
];
