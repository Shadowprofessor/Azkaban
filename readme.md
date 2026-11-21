# GhostPrint

GhostPrint audits Google Takeout, Instagram, and Spotify exports on your laptop. It maps which categories appear in the supplied files and builds a prioritized remediation report with steps linked to public platform guidance.

## Run the hackathon demo

Run this in PowerShell from the repository root with Python 3.11 or newer. The local pipeline uses the Python standard library.

```powershell
python -m ghostprint demo
```

Open [the local dashboard](http://127.0.0.1:8765). Click a cell to open its evidence and recommended action. The demo ZIP is synthetic. The dashboard can download the report as JSON.

## Audit websites as you browse

```powershell
python -m ghostprint live
```

1. In Chrome, open `chrome://extensions`. In Edge, open `edge://extensions`.
2. Enable Developer mode and choose **Load unpacked**. Select the repository's `browser-companion` folder.
3. In [GhostPrint](http://127.0.0.1:8765), open **Pair browser companion** and copy the code. Paste it into the extension popup, choose **Start recording**, and accept the browser's optional tab permission.
4. Visit a few websites. The dashboard shows foreground hostnames and recent counts. Choose **Pause recording** in the extension or **Clear activity** in the dashboard at any time.
5. To find site-specific evidence, use **Find privacy links on this page** in the extension. In GhostPrint, click the site's hostname to see any same-site privacy links found and general steps. You can also type a hostname without installing the extension and ask about permissions, cookies, or account deletion.

Type or dictate a privacy prompt, then click **Send** or press Enter. The **Answer** panel shows the recommended steps and their sources. Press Shift+Enter to add a line to the prompt.

Turn on **Search the web if there’s no local answer** to look up public questions when the local guides have no match. This preference lasts for the browser tab. The search provider receives the question or the English lookup from dictation. The selected website, archive report, recorded browsing activity and microphone audio stay local. GhostPrint skips web lookup for prompts with patterns such as email addresses, credentials or full URLs.

The web fallback searches English Wikipedia by default and displays linked excerpts. To use general web search, set `$env:BRAVE_SEARCH_API_KEY = '<your Brave Search API key>'` before starting GhostPrint. The app uses that key for [Brave Search](https://api-dashboard.search.brave.com/api-reference/web/search/get). Restart the local dashboard after changing the key.

Live recording covers ordinary browser tabs with public-style HTTP(S) hostnames in paired Chrome or Edge sessions. Browser-internal pages, incognito, other desktop apps, full navigation paths, queries, page contents, form input, and credentials are outside that recording scope. The optional link scan reads matching same-origin links when explicitly requested. Activity is kept in the dashboard's memory and expires when it exits. Copy a new code after restarting.

## Turn on offline voice

On Windows, run this once from the repository root using Python 3.12. The setup downloads the multilingual model. Dictation and read-aloud run offline afterward.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-voice.txt
.\.venv\Scripts\python.exe -c "from faster_whisper.utils import download_model; download_model('small', output_dir='.voice-models/small')"
.\.venv\Scripts\python.exe -m ghostprint live --voice-model .voice-models/small
```

Use **Use microphone**, allow the browser to access it, speak, and choose **Stop recording**. Review or edit the resulting prompt. Choose the dictation language explicitly for short recordings or when automatic detection picks the wrong language. For supported spoken languages, Whisper preserves the original transcript and shows the English lookup for the curated privacy guides. The English lookup applies to the original transcript. The guide corpus and answers are in English.

Choose **Read prompt aloud** to hear the text. Automatic mode uses the detected language for dictated text, a script-based default for several typed languages, or the browser language. Pick a specific offline language from the voice menu to override it. Read-aloud uses installed local browser voices or eSpeak NG voices. Speech quality and language coverage depend on the model and voice. The microphone audio and prompt stay on your laptop.

Use the same `--voice-model` option with `demo` or `audit --serve` to show browsing, voice, and archives together. Use `--port 8767` if another GhostPrint is already listening, and enter that port in the extension popup.

## Audit real exports

```powershell
python -m ghostprint audit 'C:\exports\takeout.zip' 'C:\exports\instagram.zip' 'C:\exports\spotify' --serve
python -m ghostprint audit 'C:\exports\spotify.zip' --platform Spotify --output ghostprint-report.json
```

The dashboard listens only on loopback. Keep real reports on the audit laptop. A report can contain filenames, activity counts and hours, and Spotify artist names. Close the process to stop serving the report. Reports are written only when requested.

| Platform | Formats and signals covered |
| --- | --- |
| Google | Maps Timeline JSON, activity JSON and recognized Takeout HTML cards, contacts in vCard or CSV, and recognized ad topic JSON |
| Instagram | JSON exports with synced contacts, followers and following, messages, login activity, and ad topics |
| Spotify | Standard and extended streaming-history JSON, inference and follower files, and the presence of country and IP fields |

Import coverage shows unreadable, unrecognized, and size-limited files. Export formats vary. A blank cell means the scan found no supported records in that category. Counts are export rows, and overlapping export bundles can include the same records. Activity charts use parseable timestamps in UTC. Repeated Spotify artists are labeled as inferred preferences. Streaming IP presence and a connection country are weaker signals than GPS history or unfamiliar account sessions. Scores are heuristic priorities for review.

## Run the local evaluation

```powershell
python -m ghostprint evaluate --output ghostprint-evaluation.json
python -m unittest discover -s tests -v
```

The evaluator compares plain BM25 against BM25 with platform filtering and privacy-topic matching. It checks 20 answerable development questions, 4 out-of-scope development questions, 14 answerable holdout questions, 3 out-of-scope holdout questions, and a synthetic archive spanning all three platforms.

| Retrieval | Development Top-1 | Holdout Top-1 | Holdout Recall@5 | Holdout abstentions |
| --- | ---: | ---: | ---: | ---: |
| BM25 | 75% | 85.7% | 100% | 0/3 |
| Platform and topic matching + BM25 | 100% | 92.9% | 100% | 3/3 |

These results come from a small, authored benchmark. The per-case JSON includes ranked IDs, latency, and errors. Archive smoke checks verify expected counts and guide IDs, first priority, the UTC activity peak, and the inferred listening preference.

## Connect the second laptop to Nemotron

The audit laptop runs parsing, retrieval, and report generation. The model laptop runs the benchmark bridge and forwards fixed synthetic questions and retrieved public guide text to NVIDIA. Real audits do not call the bridge. The bridge accepts only predefined benchmark IDs, and model results can contain only guide IDs retrieved for that case. This keeps archive contents and derived findings on the audit laptop.

On the **model laptop**, make the repository available and set these variables in the shell that starts the bridge. Use a freshly rotated NVIDIA API key and a separate shared token.

```powershell
$env:NVIDIA_API_KEY = '<fresh NVIDIA key>'
$env:GHOSTPRINT_BRIDGE_TOKEN = '<shared token>'
python -m ghostprint bridge --host 0.0.0.0 --port 8766
```

Use the model laptop's LAN IPv4 address from `ipconfig`. Use a trusted private LAN, and if Windows Firewall prompts, allow the port only for this connection on the private network. On the **audit laptop**, run this with the same shared token.

```powershell
$env:GHOSTPRINT_BRIDGE_TOKEN = '<shared token>'
python -m ghostprint demo --model-server 'http://<model-laptop-ip>:8766'
python -m ghostprint evaluate --model-server 'http://<model-laptop-ip>:8766' --output ghostprint-evaluation.json
```

The dashboard demo shows which public guides the model selected for a fictional Google Maps Timeline question. Run the evaluator separately to compare model ranking with local retrieval.

The bridge defaults to [NVIDIA's hosted Nemotron 3 Ultra 550B A55B endpoint](https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b/apireference). For an existing OpenAI-compatible endpoint on the model laptop, pass `--base-url http://127.0.0.1:8000/v1 --model <served-model-id>` to the bridge. If that endpoint requires authorization, set `GHOSTPRINT_MODEL_TOKEN` on the model laptop. NVIDIA lists multi-GPU infrastructure for [self-hosting this Ultra model](https://build.nvidia.com/nvidia/nemotron-3-ultra-550b-a55b/modelcard).

## How grounding works

Archive rows are summarized into platform and category findings. Only those controlled labels enter audit retrieval. The local index ranks a bundled, section-sized corpus of public actions. The report generator combines the retrieved steps and source URL with local evidence and priority. You can inspect retrieval independently.

```powershell
python -m ghostprint retrieve 'How can I delete my Google Maps travel history?'
```

The attached build spec describes a separate legal-verdict workflow for suspected leaks. This archive auditor uses its public-source grounding and metadata filtering approach. The implemented corpus contains platform remediation guidance. Meta's account controls may require sign-in, and options can vary by account or region.
