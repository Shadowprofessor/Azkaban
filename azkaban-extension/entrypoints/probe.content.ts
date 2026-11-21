// MAIN-world probe (document_start, before page scripts). Observes only:
// every hook calls straight through to the original API inside try/catch, so the page
// behaves exactly as without the extension. Findings go to the isolated bridge via
// window.postMessage; MAIN world has no extension API access by design.
import { defineContentScript } from "wxt/utils/define-content-script";

export const CHANNEL = "__azkaban_probe__";

export default defineContentScript({
  matches: ["<all_urls>"],
  runAt: "document_start",
  world: "MAIN",
  allFrames: true,
  main() {
    type Surface = "canvas" | "webgl" | "audio" | "font" | "device" | "screen";
    const WINDOW_MS = 2000;
    const FLAG_AT = 5;
    const hits: { s: Surface; t: number }[] = [];
    const counts: Record<Surface, number> = { canvas: 0, webgl: 0, audio: 0, font: 0, device: 0, screen: 0 };
    let flagged = false;
    let reportTimer: ReturnType<typeof setTimeout> | null = null;

    const post = (payload: Record<string, unknown>) => {
      try {
        window.postMessage({ [CHANNEL]: true, ...payload }, "*");
      } catch {
        /* never break the page */
      }
    };

    const note = (s: Surface) => {
      try {
        const now = Date.now();
        counts[s]++;
        hits.push({ s, t: now });
        while (hits.length && now - hits[0]!.t > WINDOW_MS) hits.shift();
        const distinct = new Set(hits.map((h) => h.s)).size;
        if (!flagged && distinct >= FLAG_AT) {
          flagged = true;
          post({ kind: "fingerprint", flagged: true, surfaces: distinct, counts: { ...counts } });
        }
        if (!reportTimer) {
          reportTimer = setTimeout(() => {
            reportTimer = null;
            const surfaces = Object.values(counts).filter((n) => n > 0).length;
            post({ kind: "fingerprint", flagged, surfaces, counts: { ...counts } });
          }, 1500);
        }
      } catch {
        /* ignore */
      }
    };

    // Wrap a prototype method: count, then call the original with the same this/args.
    const wrap = (proto: object | undefined, name: string, s: Surface, when?: (args: unknown[]) => boolean) => {
      try {
        if (!proto) return;
        const desc = Object.getOwnPropertyDescriptor(proto, name);
        const orig = desc?.value;
        if (typeof orig !== "function") return;
        const wrapped = function (this: unknown, ...args: unknown[]) {
          try {
            if (!when || when(args)) note(s);
          } catch {
            /* ignore */
          }
          return orig.apply(this, args);
        };
        Object.defineProperty(wrapped, "name", { value: orig.name });
        Object.defineProperty(wrapped, "length", { value: orig.length });
        Object.defineProperty(proto, name, { ...desc, value: wrapped });
      } catch {
        /* leave the original untouched */
      }
    };

    // Wrap a getter (navigator.hardwareConcurrency, screen.width, ...).
    const wrapGetter = (proto: object | undefined, name: string, s: Surface) => {
      try {
        if (!proto) return;
        const desc = Object.getOwnPropertyDescriptor(proto, name);
        if (!desc?.get) return;
        const get = desc.get;
        Object.defineProperty(proto, name, {
          ...desc,
          get(this: unknown) {
            note(s);
            return get.call(this);
          },
        });
      } catch {
        /* ignore */
      }
    };

    const g = globalThis as unknown as Record<string, { prototype?: object } | undefined>;
    // Canvas
    wrap(g.HTMLCanvasElement?.prototype, "toDataURL", "canvas");
    wrap(g.HTMLCanvasElement?.prototype, "toBlob", "canvas");
    wrap(g.CanvasRenderingContext2D?.prototype, "getImageData", "canvas");
    wrap(g.OffscreenCanvasRenderingContext2D?.prototype, "getImageData", "canvas");
    // Fonts: measuring text in many fonts, or probing installed fonts
    wrap(g.CanvasRenderingContext2D?.prototype, "measureText", "font");
    wrap(g.FontFaceSet?.prototype, "check", "font");
    // WebGL: unmasked vendor/renderer and pixel readback
    const DEBUG_PARAMS = new Set([37445, 37446]); // UNMASKED_VENDOR_WEBGL / UNMASKED_RENDERER_WEBGL
    for (const ctx of [g.WebGLRenderingContext, g.WebGL2RenderingContext]) {
      wrap(ctx?.prototype, "getParameter", "webgl", (a) => DEBUG_PARAMS.has(a[0] as number));
      wrap(ctx?.prototype, "getExtension", "webgl", (a) => String(a[0]).includes("debug_renderer"));
      wrap(ctx?.prototype, "readPixels", "webgl");
    }
    // Audio
    wrap(g.OfflineAudioContext?.prototype, "startRendering", "audio");
    wrap(g.AudioBuffer?.prototype, "getChannelData", "audio");
    wrap(g.AnalyserNode?.prototype, "getFloatFrequencyData", "audio");
    // Device
    for (const p of ["hardwareConcurrency", "deviceMemory", "platform", "plugins", "mimeTypes", "maxTouchPoints"]) {
      wrapGetter(g.Navigator?.prototype, p, "device");
    }
    wrap(g.Navigator?.prototype, "getBattery", "device");
    wrap(g.MediaDevices?.prototype, "enumerateDevices", "device");
    wrap(g.NavigatorUAData?.prototype, "getHighEntropyValues", "device");
    // Screen
    for (const p of ["width", "height", "colorDepth", "pixelDepth", "availWidth", "availHeight"]) {
      wrapGetter(g.Screen?.prototype, p, "screen");
    }

    // ---------------------------------------------------------------- outbound bodies
    // fetch / XHR / sendBeacon: copy the URL and (bounded) body, then call the original.
    const MAX_BODY = 16 * 1024;
    const report = (url: unknown, method: string, body: string) => {
      try {
        const u = String(url ?? "").slice(0, 4096);
        if (!u || (!body && !u.includes("?"))) return;
        post({ kind: "net", url: new URL(u, location.href).href, method: method.toUpperCase(), body: body.slice(0, MAX_BODY), ts: Date.now() });
      } catch {
        /* ignore */
      }
    };
    const utf8 = (b: ArrayBuffer | ArrayBufferView) => {
      try {
        const view = b instanceof ArrayBuffer ? new Uint8Array(b, 0, Math.min(b.byteLength, MAX_BODY)) : new Uint8Array(b.buffer, b.byteOffset, Math.min(b.byteLength, MAX_BODY));
        return new TextDecoder().decode(view);
      } catch {
        return "";
      }
    };
    // Returns the body text, or a promise for types that must be read asynchronously.
    // Never consumes a stream the page still needs.
    const bodyOf = (b: unknown): string | Promise<string> => {
      try {
        if (b == null) return "";
        if (typeof b === "string") return b.slice(0, MAX_BODY);
        if (b instanceof URLSearchParams) return b.toString().slice(0, MAX_BODY);
        if (b instanceof FormData) {
          const p = new URLSearchParams();
          for (const [k, v] of b) if (typeof v === "string") p.append(k, v);
          return p.toString().slice(0, MAX_BODY);
        }
        if (b instanceof ArrayBuffer || ArrayBuffer.isView(b)) return utf8(b as ArrayBuffer);
        if (b instanceof Blob && b.size <= 4 * MAX_BODY) return b.slice(0, MAX_BODY).text().catch(() => "");
      } catch {
        /* ignore */
      }
      return "";
    };
    const emit = (url: unknown, method: string, body: unknown) => {
      try {
        const t = bodyOf(body);
        if (typeof t === "string") report(url, method, t);
        else void t.then((s) => report(url, method, s));
      } catch {
        /* ignore */
      }
    };

    try {
      const origFetch = window.fetch;
      if (typeof origFetch === "function") {
        const patched = function (this: unknown, input: RequestInfo | URL, init?: RequestInit) {
          try {
            if (input instanceof Request) {
              const method = init?.method ?? input.method;
              if (init?.body !== undefined) emit(input.url, method, init.body);
              else if (!input.bodyUsed && method !== "GET" && method !== "HEAD") {
                input.clone().text().then((s) => report(input.url, method, s), () => report(input.url, method, ""));
              } else report(input.url, method, "");
            } else {
              emit(String(input), init?.method ?? "GET", init?.body);
            }
          } catch {
            /* ignore */
          }
          return origFetch.apply(this as typeof window, [input, init] as [RequestInfo | URL, RequestInit | undefined]);
        };
        Object.defineProperty(patched, "name", { value: "fetch" });
        window.fetch = patched as typeof window.fetch;
      }
    } catch {
      /* leave fetch alone */
    }

    try {
      const meta = new WeakMap<XMLHttpRequest, { method: string; url: string }>();
      const origOpen = XMLHttpRequest.prototype.open;
      const origSend = XMLHttpRequest.prototype.send;
      XMLHttpRequest.prototype.open = function (this: XMLHttpRequest, method: string, url: string | URL, ...rest: unknown[]) {
        try {
          meta.set(this, { method, url: String(url) });
        } catch {
          /* ignore */
        }
        return (origOpen as (...a: unknown[]) => void).call(this, method, url, ...rest);
      } as typeof XMLHttpRequest.prototype.open;
      XMLHttpRequest.prototype.send = function (this: XMLHttpRequest, body?: Document | XMLHttpRequestBodyInit | null) {
        try {
          const m = meta.get(this);
          if (m) emit(m.url, m.method, body);
        } catch {
          /* ignore */
        }
        return origSend.call(this, body);
      };
    } catch {
      /* leave XHR alone */
    }

    try {
      const origBeacon = Navigator.prototype.sendBeacon;
      if (typeof origBeacon === "function") {
        Navigator.prototype.sendBeacon = function (this: Navigator, url: string | URL, data?: BodyInit | null) {
          try {
            emit(String(url), "POST", data);
          } catch {
            /* ignore */
          }
          return origBeacon.call(this, url, data);
        };
      }
    } catch {
      /* leave sendBeacon alone */
    }
  },
});
