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
  },
});
