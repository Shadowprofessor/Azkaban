import { unknownTrackerToast, fingerprintToast, thirdPartyToast, shouldSend, UNKNOWN_CONFIDENCE_MIN, THIRD_PARTY_MIN, MAX_PER_PAGE } from "../lib/alerts.ts";
let fail = 0;
const ok = (c, m) => { if (!c) { console.log("FAIL " + m); fail++; } else console.log("ok   " + m); };

ok(unknownTrackerToast("quietpixel.io", 0.92)?.message === "Unknown tracker detected: quietpixel.io (92% confidence)", "unknown tracker message text");
ok(unknownTrackerToast("quietpixel.io", 0.92)?.severity === "warning", "unknown tracker is a warning");
ok(unknownTrackerToast("q.io", 0.84) === null, "below threshold does not toast");
ok(unknownTrackerToast("q.io", UNKNOWN_CONFIDENCE_MIN) !== null, "exactly at threshold does toast");
ok(unknownTrackerToast("", 0.99) === null, "no domain, no toast");
ok(unknownTrackerToast("q.io", NaN) === null, "NaN confidence does not toast");

ok(fingerprintToast(true, 5).message === "Canvas fingerprinting blocked on this page", "blocked fingerprint text");
ok(fingerprintToast(false, 5).message.includes("5/6"), "unblocked fingerprint names surfaces");
ok(fingerprintToast(true, 5).severity === "critical", "fingerprinting is critical");

ok(thirdPartyToast(19) === null, "19 third parties is quiet");
ok(thirdPartyToast(23)?.message === "This page made 23 third-party requests", "third-party message text");
ok(thirdPartyToast(23).key === thirdPartyToast(29).key, "same bucket dedupes");
ok(thirdPartyToast(23).key !== thirdPartyToast(41).key, "next bucket re-toasts");

ok(shouldSend([], "a") === true, "first toast allowed");
ok(shouldSend(["a"], "a") === false, "duplicate suppressed");
ok(shouldSend(["a", "b", "c"], "d") === false, `page cap of ${MAX_PER_PAGE} enforced`);
ok(shouldSend(["a", "b"], "c") === true, "under the cap allowed");
console.log(fail ? `\n${fail} FAILURES` : "\nall alert checks pass");
process.exit(fail ? 1 : 0);
