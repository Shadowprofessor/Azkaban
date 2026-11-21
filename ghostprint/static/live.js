const ui = (id) => document.getElementById(id);
const promptField = ui("ask-prompt");
const siteField = ui("ask-site");
const askForm = ui("ask-form");
const sendButton = ui("send-prompt");
const webToggle = ui("search-web");
const recorderButton = ui("record-voice");
const tts = window.speechSynthesis;
let transcript;
let recording;
let activityKey;
let askRequest = 0;
let playback = 0;
let readLanguages = [];
let speechUrl;

webToggle.checked = sessionStorage.getItem("ghostprint-web-fallback") === "enabled";
webToggle.addEventListener("change", () => {
  sessionStorage.setItem("ghostprint-web-fallback", webToggle.checked ? "enabled" : "disabled");
});

async function localRequest(url, options) {
  const response = await fetch(url, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "GhostPrint could not complete the request.");
  return data;
}

function submitJson(url, data) {
  return localRequest(url, { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data) });
}

function localNode(tag, text, target) {
  const el = document.createElement(tag);
  el.textContent = text;
  target.append(el);
  return el;
}

function linkTo(title, url, target) {
  const link = localNode("a", title, target);
  link.href = url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
}

async function refreshSites() {
  const target = ui("recent-sites");
  try {
    const { sites } = await localRequest("/api/live");
    const key = JSON.stringify(sites);
    if (key === activityKey) return;
    activityKey = key;
    target.replaceChildren();
    ui("clear-activity").disabled = !sites.length;
    if (!sites.length) localNode("p", "Waiting for website activity.", target);
    for (const item of sites) {
      const button = localNode("button", `${item.site} · ${item.visits}`, target);
      button.type = "button";
      button.title = `Last recorded at ${new Date(item.seen).toLocaleString()}`;
      button.addEventListener("click", () => {
        siteField.value = item.site;
        runQuestion();
      });
    }
  } catch {
    activityKey = undefined;
    target.textContent = "The local dashboard is disconnected.";
  }
}

ui("clear-activity").addEventListener("click", async () => {
  try {
    await submitJson("/api/live/clear", {});
    askRequest++;
    sendButton.disabled = false;
    ui("ask-answer").hidden = true;
    ui("ask-result").replaceChildren();
    ui("ask-status").textContent = "";
    siteField.value = "";
    await refreshSites();
  } catch (error) {
    ui("pair-status").textContent = error.message;
  }
});

async function runQuestion() {
  const id = ++askRequest;
  const status = ui("ask-status");
  const panel = ui("ask-answer");
  const target = ui("ask-result");
  const spoken = transcript?.text === promptField.value ? transcript : undefined;
  const prompt = (spoken?.lookup || promptField.value).trim();
  const site = siteField.value.trim();
  const searchWeb = webToggle.checked;
  panel.hidden = false;
  target.replaceChildren();
  if (!prompt && !site) {
    status.textContent = "Enter a question or choose a website first.";
    sendButton.disabled = false;
    promptField.focus();
    return;
  }
  sendButton.disabled = true;
  status.textContent = searchWeb ? "Checking local guides first…" : "Searching local guides…";
  try {
    const answer = await submitJson("/api/live/ask", { site, prompt, search_web: searchWeb });
    if (id !== askRequest) return;
    status.textContent = answer.site ? `Guidance for ${answer.site}` : "Based on local privacy guides.";
    for (const guide of answer.guides) {
      const article = localNode("article", "", target);
      localNode("h4", guide.title, article);
      const list = localNode("ol", "", article);
      for (const step of guide.steps) localNode("li", step, list);
      linkTo("Open source", guide.url, article);
    }
    if (!answer.guides.length) {
      const web = answer.web;
      if (web?.status === "ok") {
        status.textContent = `Found online · ${web.provider}`;
        for (const source of web.sources) {
          const article = localNode("article", "", target);
          localNode("h4", source.title, article);
          localNode("p", source.snippet, article);
          linkTo("Open web source", source.url, article);
        }
      } else if (web?.status === "blocked") {
        status.textContent = "This question may contain private details. Remove them and send it again to search online.";
      } else if (web?.status === "too_long") {
        status.textContent = "Shorten your question to 500 characters and 70 words or fewer to search online.";
      } else if (web?.status === "unavailable") {
        status.textContent = "The web search provider did not respond. Try again in a moment.";
      } else if (web) {
        status.textContent = "No matching web sources. Try a shorter or more specific question.";
      } else {
        status.textContent = "No matching local answer. Turn on web search to look for public sources.";
      }
    }
    if (answer.links.length) {
      const article = localNode("article", "", target);
      localNode("h4", "Privacy links found on the page", article);
      const list = localNode("ul", "", article);
      for (const url of answer.links) linkTo(url, url, localNode("li", "", list));
    }
    ui("answer-heading").scrollIntoView({ block: "nearest" });
  } catch (error) {
    if (id === askRequest) {
      status.textContent = error instanceof TypeError ? "Could not reach GhostPrint. Check that the local dashboard is running, then try again." : error.message;
    }
  } finally {
    if (id === askRequest) sendButton.disabled = false;
  }
}

askForm.addEventListener("submit", (event) => {
  event.preventDefault();
  runQuestion();
});

promptField.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
    event.preventDefault();
    if (!sendButton.disabled) askForm.requestSubmit();
  }
});

ui("copy-pairing").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(ui("pairing-code").value);
    ui("pair-status").textContent = "Pairing code copied.";
  } catch {
    ui("pair-status").textContent = "Show the code and copy it manually.";
  }
});
ui("show-pairing").addEventListener("click", () => {
  const input = ui("pairing-code");
  input.type = input.type === "password" ? "text" : "password";
  ui("show-pairing").textContent = input.type === "password" ? "Show code" : "Hide code";
});

recorderButton.addEventListener("click", async () => {
  const status = ui("voice-status");
  if (recording) {
    if (recording.state === "recording") recording.stop();
    return;
  }
  recorderButton.disabled = true;
  let stream;
  try {
    stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    const recorder = new MediaRecorder(stream);
    const language = ui("dictation-language").value;
    const chunks = [];
    const stopRecording = () => {
      if (recorder.state === "recording") recorder.stop();
      stream.getTracks().forEach((track) => track.stop());
    };
    const timeout = setTimeout(stopRecording, 30_000);
    recorder.ondataavailable = (event) => chunks.push(event.data);
    recorder.onstop = async () => {
      clearTimeout(timeout);
      stopRecording();
      window.removeEventListener("pagehide", stopRecording);
      recorderButton.disabled = true;
      status.textContent = "Transcribing on this laptop…";
      try {
        const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        transcript = await localRequest("/api/voice", { method: "POST", body: blob,
          headers: { "X-GhostPrint-Language": language } });
        if (transcript.text) {
          promptField.value = transcript.text.slice(0, 1500);
          transcript.text = promptField.value;
          status.textContent = `Detected ${transcript.language}. Review the transcript before submitting.`;
        } else {
          status.textContent = "No speech was detected. Try again.";
        }
        updateReadButton();
        showTranslation();
      } catch (error) {
        status.textContent = error.message;
      } finally {
        recording = undefined;
        recorderButton.disabled = false;
        recorderButton.textContent = "Use microphone";
      }
    };
    recorder.start();
    recording = recorder;
    window.addEventListener("pagehide", stopRecording, { once: true });
    recorderButton.disabled = false;
    recorderButton.textContent = "Stop recording";
    status.textContent = "Recording for up to 30 seconds.";
  } catch {
    stream?.getTracks().forEach((track) => track.stop());
    recorderButton.disabled = false;
    status.textContent = "Could not start the microphone. Check browser permission and device access.";
  }
});

let voices = [];
function updateReadButton() {
  ui("read-prompt").disabled = !promptField.value.trim() || !(voices.length || readLanguages.length);
}

function refreshVoices() {
  const select = ui("local-voices");
  const previous = select.value;
  voices = (tts?.getVoices() ?? []).filter((voice) => voice.localService);
  select.replaceChildren(new Option("Automatic", ""));
  for (const voice of voices) select.add(new Option(`${voice.name} (${voice.lang})`, `system:${voice.voiceURI}`));
  const languageNames = new Intl.DisplayNames([navigator.language], { type: "language" });
  for (const code of readLanguages) {
    let name = code;
    try { name = languageNames.of(code) || code; } catch { /* Use the original language code. */ }
    select.add(new Option(`${name} · offline`, `offline:${code}`));
  }
  if ([...select.options].some((option) => option.value === previous)) select.value = previous;
  select.disabled = !(voices.length || readLanguages.length);
  updateReadButton();
}

function showTranslation() {
  const line = ui("lookup-translation");
  line.hidden = !(transcript?.text === promptField.value && transcript.lookup
    && transcript.text !== transcript.lookup);
  line.textContent = line.hidden ? "" : `English guide lookup: ${transcript.lookup}`;
}

promptField.addEventListener("input", () => {
  updateReadButton();
  showTranslation();
});
tts?.addEventListener("voiceschanged", refreshVoices);
refreshVoices();

function stopReading() {
  playback++;
  tts?.cancel();
  const audio = ui("spoken-audio");
  audio.pause();
  audio.removeAttribute("src");
  audio.hidden = true;
  if (speechUrl) URL.revokeObjectURL(speechUrl);
  speechUrl = undefined;
  ui("stop-reading").hidden = true;
}

function promptLanguage(text) {
  if (transcript?.text === promptField.value) return transcript.language;
  const scripts = [
    [/\p{Script=Devanagari}/u, "hi"], [/\p{Script=Bengali}/u, "bn"],
    [/\p{Script=Tamil}/u, "ta"], [/\p{Script=Telugu}/u, "te"],
    [/\p{Script=Kannada}/u, "kn"], [/\p{Script=Malayalam}/u, "ml"],
    [/\p{Script=Gujarati}/u, "gu"], [/\p{Script=Gurmukhi}/u, "pa"],
    [/\p{Script=Arabic}/u, "ar"], [/\p{Script=Cyrillic}/u, "ru"],
    [/\p{Script=Hiragana}|\p{Script=Katakana}/u, "ja"], [/\p{Script=Hangul}/u, "ko"],
    [/\p{Script=Han}/u, "cmn"], [/\p{Script=Hebrew}/u, "he"],
  ];
  return scripts.find(([script]) => script.test(text))?.[1] ?? navigator.language;
}

ui("read-prompt").addEventListener("click", async () => {
  stopReading();
  const current = playback;
  const text = promptField.value.trim();
  const language = promptLanguage(text);
  const code = language.toLowerCase().split("-")[0];
  const aliases = { zh: "cmn", yue: "yue", jw: "jv" };
  const offlineCode = aliases[code] || code;
  const choice = ui("local-voices").value;
  const voice = choice
    ? voices.find((item) => `system:${item.voiceURI}` === choice)
    : voices.find((item) => item.lang.toLowerCase().split("-")[0] === code);
  const status = ui("voice-status");
  status.textContent = "";
  if (voice) {
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.voice = voice;
    utterance.lang = voice.lang;
    const done = () => {
      if (current === playback) ui("stop-reading").hidden = true;
    };
    utterance.onend = done;
    utterance.onerror = () => {
      done();
      if (current === playback) status.textContent = "The local voice could not read this prompt.";
    };
    ui("stop-reading").hidden = false;
    tts.speak(utterance);
    return;
  }
  const offline = choice.startsWith("offline:") ? choice.slice(8) :
    readLanguages.find((item) => item === offlineCode) ||
    readLanguages.find((item) => item.split("-")[0] === offlineCode);
  if (!offline) {
    status.textContent = `Choose a local read-aloud voice for ${language}.`;
    return;
  }
  try {
    ui("stop-reading").hidden = false;
    const response = await fetch("/api/read", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ prompt: text, language: offline }) });
    if (!response.ok) throw new Error((await response.json()).error);
    const wav = await response.blob();
    if (current !== playback) return;
    const audio = ui("spoken-audio");
    speechUrl = URL.createObjectURL(wav);
    audio.src = speechUrl;
    audio.hidden = false;
    audio.play().catch(() => { status.textContent = "Press play to hear this prompt."; });
  } catch (error) {
    if (current === playback) {
      stopReading();
      status.textContent = error.message;
    }
  }
});
ui("stop-reading").addEventListener("click", stopReading);

localRequest("/api/live/settings").then((data) => {
  ui("pairing-code").value = data.pairing_code;
  readLanguages = data.read_languages;
  refreshVoices();
  const languages = ui("dictation-language");
  const display = new Intl.DisplayNames([navigator.language], { type: "language" });
  for (const code of data.dictation_languages) languages.add(new Option(display.of(code) || code, code));
  languages.disabled = !data.voice;
  recorderButton.disabled = !(data.voice && window.MediaRecorder && navigator.mediaDevices?.getUserMedia);
  if (recorderButton.disabled) {
    ui("voice-status").textContent = data.voice ? "Microphone recording is unavailable in this browser."
      : "Start GhostPrint with a local Whisper model to enable dictation.";
  }
}).catch((error) => {
  ui("pair-status").textContent = error.message;
});
refreshSites();
setInterval(refreshSites, 2500);
