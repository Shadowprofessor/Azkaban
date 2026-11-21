# GhostPrint

GhostPrint audits Google Takeout, Instagram, and Spotify exports on your laptop. It maps which categories appear in the supplied files and builds a prioritized remediation report with steps linked to public platform guidance.

## Run the hackathon demo

Run this in PowerShell from the repository root with Python 3.11 or newer. The local pipeline uses the Python standard library.

```powershell
python -m ghostprint demo
```

Open [the local dashboard](http://127.0.0.1:8765). Click a cell to open its evidence and recommended action. The demo ZIP is synthetic. The dashboard can download the report as JSON.

## Connect an account

In **Connect an account**, choose **Connect** and approve access on the provider’s website. GhostPrint automatically fetches the authorized records and shows findings, evidence, an exposure score when supported, and steps to reduce exposure. **Refresh snapshot** fetches current records during the session. **Disconnect** clears the local token and report. To revoke the OAuth grant at the provider, use **Manage provider access**.

| Connection | What GhostPrint checks |
| --- | --- |
| Google Contacts | Saved contact counts and how many records include an email or phone field |
| GitHub | Account email counts and whether GitHub marks any address public |

These are scoped API snapshots. Other Google data, Spotify data, and other unsupported private account data can be reviewed through supported exports. **Website privacy check** checks any reachable public policy and terms pages without a sign-in or upload. Pair the browser companion to compare a site’s statements with a local browser observation.

Set up either provider before starting the dashboard:

1. For Google, enable the People API in your Google Cloud project and create a **Desktop app** OAuth client. Configure the consent screen and add your Google account as a test user if the app is in testing. [Google desktop OAuth setup](https://developers.google.com/identity/protocols/oauth2/native-app) · [Google Contacts endpoint](https://developers.google.com/people/api/rest/v1/people.connections/list)
2. For GitHub, register an OAuth app and set its authorization callback URL to `http://127.0.0.1:8765/`. Use the same port as the dashboard. [Register a GitHub OAuth app](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/creating-an-oauth-app) · [GitHub email endpoint](https://docs.github.com/en/rest/users/emails#list-email-addresses-for-the-authenticated-user)

In the PowerShell session that starts GhostPrint, set the two variables for each provider you enabled. Keep the actual values out of source control.

```powershell
$env:GOOGLE_OAUTH_CLIENT_ID = '<Google desktop client ID>'
$env:GOOGLE_OAUTH_CLIENT_SECRET = '<Google desktop client secret>'
$env:GITHUB_OAUTH_CLIENT_ID = '<GitHub OAuth app client ID>'
$env:GITHUB_OAUTH_CLIENT_SECRET = '<GitHub OAuth app client secret>'
python -m ghostprint live --port 8765
```

GhostPrint contacts the selected provider for sign-in and the API pull. Only aggregate evidence appears in the review. Account snapshots and access tokens stay in memory on the laptop running the dashboard, with access tokens usable by GhostPrint for up to one hour. The account review runs locally and sends no records to a model or search service.

## Audit websites as you browse

```powershell
python -m ghostprint live
```

1. In Chrome, open `chrome://extensions`. In Edge, open `edge://extensions`.
2. Enable Developer mode and choose **Load unpacked**. Select the repository's `browser-companion` folder.
3. In [GhostPrint](http://127.0.0.1:8765), open **Pair browser companion** and copy the code. Paste it into the extension popup, choose **Start recording**, and accept the browser's optional tab permission.
4. Visit a few websites. The dashboard shows foreground hostnames and recent counts. Choose **Pause recording** in the extension or **Clear activity** in the dashboard at any time.
5. To find site-specific evidence, use **Capture website privacy evidence** in the extension. Then select the site's hostname in GhostPrint and choose **Check policies**. PrivacyGPT can also report aggregate browser permission grants from explicit checks.

## Check a website's privacy policy and terms

PrivacyGPT shows the data it found alongside the prioritized findings. Website reviews include public policy disclosures and the available browser evidence. Import reviews list recognized record types and link to file coverage. Connected accounts show how many authorized records were examined. A score requires evidence that supports a finding.

If a public policy document is readable, **Search the web for public privacy reports** opens a search using the website hostname. Search results are external leads to verify before treating them as findings.

Use **Check a website without signing in** or **Choose an open tab** in Chrome or Edge with the updated GhostPrint companion. Open the dashboard in the same browser profile as the tabs you want to check. If you already loaded the companion, click **Reload** for it on the browser’s extensions page, then reload the dashboard. The first time the browser needs permission to list tabs, select **Show open tabs** and approve the prompt. The picker shows the tab titles and website names. Choose a tab and allow one-time page inspection to start the review. The rest of the tab list stays in the picker. Account sign-in, file upload, and recording are optional. Browser settings, local files, native desktop apps, and tabs in other browser profiles are outside this picker’s scope. [Chrome extension permission controls](https://developer.chrome.com/docs/extensions/reference/api/permissions)

For a public-document check without the companion, enter a public HTTPS hostname and select **Check policies**. GhostPrint reads the website's public documents and shows short, linked statements about collection, use, storage, retention, sharing, and sale. When discovery misses a document, use the specific policy link option. The policy reader makes public requests without account credentials and strips query strings. It can read supported HTML, plain-text, and text-based PDF documents. A blocked or unreadable document is marked unavailable.

If an address check only shows public documents, choose **Capture this website’s tab** to find its open browser tab. **Capture this site again** updates the website’s PrivacyGPT findings and score when the page changes. To switch sites, click **Check another website** or **Show all website tabs** inside the picker. You can start a new check while another is running. The paired companion’s **Capture website privacy evidence** action also updates the dashboard automatically. A new capture replaces the previous snapshot for that hostname during the dashboard session. Use **Clear activity** to clear the captures. A tab on a private intranet can be reviewed using browser evidence alone when its hostname is eligible only for local capture.

The check captures visible field categories, nonempty named URL parameter categories, hostnames, permission states, and local/session-storage entry counts. The dashboard receives no field values, request bodies, full browsing URLs, or storage contents. Website scores use the strongest finding from the latest capture. The comparison distinguishes an explicit disclosure, a scoped policy statement, missing evidence, and a possible mismatch with a clear denial. Different hostnames can belong to the same organization or a service provider. A mismatch needs verification, and an apparent match only applies to the inspected evidence. GhostPrint leaves consent decisions to you.

Type or dictate a privacy prompt, then click **Send** or press Enter. The **Answer** panel shows the recommended steps and their sources. Press Shift+Enter to add a line to the prompt.

Turn on **Search the web if there’s no local answer** to look up public questions when the local guides have no match. This preference lasts for the browser tab. The search provider receives the question or the English lookup from dictation. The selected website, archive report, recorded browsing activity and microphone audio stay local. GhostPrint skips web lookup for prompts with patterns such as email addresses, credentials or full URLs.

The web fallback searches English Wikipedia by default and displays linked excerpts. To use general web search, set `$env:BRAVE_SEARCH_API_KEY = '<your Brave Search API key>'` before starting GhostPrint. The app uses that key for [Brave Search](https://api-dashboard.search.brave.com/api-reference/web/search/get). Restart the local dashboard after changing the key.

## Ask PrivacyGPT about your data

Start the demo or live dashboard. Under **Import your data**, choose the exports or audit reports you want in one review. GhostPrint analyzes them immediately. Recognized app exports use their dedicated parsers. Other files are checked by content, so a supported report does not need a recognized app name. A successful import replaces the active review. Select up to eight files totaling 512 MiB. Individual loose files are limited to 64 MiB. Raw files are stored temporarily on this laptop during processing and then deleted.

General report formats include text-based PDF, Word DOCX, Excel XLSX, CSV, TSV, JSON, JSONL/NDJSON, XML, HTML, Markdown, and plain text or log files. ZIP archives can contain these files. Enable PDF reading with `python -m pip install -r requirements-reports.txt` in the same Python environment, then restart the dashboard. Password-protected or scanned PDFs need an unlocked, searchable copy. Legacy Office binaries and image-only reports need conversion first. The general reader checks bounded portions of files, including up to 60 PDF pages, 16 worksheets and 20,000 items per file.

The generic reader recognizes labeled privacy fields and English finding text, including contact details, coordinates, IPs or device identifiers, granted permissions, government identifiers, financial identifiers, and stated audit findings. It cites a page, section, worksheet row, or record number without displaying the original sensitive value. Claims made in an uploaded audit report are marked unverified. External severity labels cannot set the GhostPrint score. A readable file with no recognized evidence remains unscored.

After upload, **Findings and fixes** lists each supported finding in priority order, with its risk, score, and steps to take. Evidence and confidence are available on each card. Concerns stated in a report are marked for verification. The score is the highest finding score, with a base determined by risk severity and a bounded adjustment for record count. Activity and interest inferences are shown separately. An import with no supported evidence remains unscored.

The **Optional privacy assistant** is below the report. Its **Analyze my imported data** mode can answer follow-up questions about the evidence.

PrivacyGPT answers from file-level counts and evidence references, shows confidence and privacy risk per finding, and ranks actions by risk and privacy benefit. It correlates supported topic labels across Google Search, YouTube, Spotify and other sources that provide readable labels. Timeline questions use parsed timestamps. Year counts can reflect incomplete coverage, and activity timestamps cannot establish when you sleep. Personal questions use the local analysis path even when web lookup is enabled.

| Source | Additional supported evidence |
| --- | --- |
| Google Takeout and YouTube | Google search and YouTube history JSON, labels and timestamps when present, coordinate presence, and explicit city and home/work labels in supported Timeline records |
| Facebook | Selected posts, contacts, search, messages, login, and Off-Meta activity JSON records |
| LinkedIn | Positions, education, connections, contacts, and selected message CSV exports |
| Twitter/X | Recognized JSON or `window.YTD` archive members |
| TikTok | Recognized watch-history lists in JSON |
| Discord | Recognized messages and account-event JSON files |
| Amazon | Order history CSV and recognized JSON order lists |
| Browser history | Chrome Takeout history JSON and selected CSV or JSON history exports |
| Chrome/Edge companion | Hostname-free activity totals and aggregate grants from explicit site permission checks |

Export layouts vary. Where files have generic names, import one service at a time with the matching `--platform` hint. The local analyzer uses a fixed set of non-sensitive topic categories. It does not assign a person's age, income, current occupation, education level, sleep schedule, or exact home or workplace address from ambiguous signals. Archive presence does not establish third-party recipients, current account settings, or retention beyond the export.

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
