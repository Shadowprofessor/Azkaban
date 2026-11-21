const accountStatus = byId("connections-status");
const accountCards = byId("account-cards");

function accountButton(label, card, account, action) {
  const button = node("button", label, card);
  button.type = "button";
  button.disabled = account.busy || !account.configured;
  button.addEventListener("click", () => updateAccount(account.id, action));
}

function showAccounts(accounts) {
  accountCards.replaceChildren();
  for (const account of accounts) {
    const card = node("article", undefined, accountCards);
    node("h3", account.title, card);
    node("p", account.description, card);
    const controls = node("div", undefined, card);
    controls.className = "controls";
    if (!account.configured) {
      node("p", "OAuth app credentials are required. See Connect an account in the README.", card);
    } else {
      if (account.connected) accountButton("Refresh snapshot", controls, account, "refresh");
      else accountButton(account.snapshot ? "Reconnect" : "Connect", controls, account, "connect");
      if (account.snapshot || account.connected || account.busy) {
        accountButton("Disconnect", controls, { ...account, busy: false }, "disconnect");
        linkTo("Manage provider access", account.grants_url, controls);
      }
    }
    if (account.busy) node("p", "Fetching the authorized records…", card);
    if (account.error) node("p", account.error, card);
    if (!account.snapshot) continue;

    const { synced_at, review } = account.snapshot;
    const checked = node("p", "Last checked ", card);
    node("time", new Date(synced_at).toLocaleString(), checked).dateTime = synced_at;
    if (review.score === null) {
      node("p", review.answer, card);
      for (const limit of review.limitations) node("p", limit, card);
    } else {
      node("p", `Exposure score · ${review.score}/100 · ${review.risk.level} risk`, card);
      showReview(review, card, "the authorized account snapshot");
    }
  }
}

async function loadAccounts() {
  const response = await fetch("/api/connections", { signal: AbortSignal.timeout(5000) });
  if (response.status === 404) throw new Error("This dashboard server is out of date. Open the updated GhostPrint dashboard.");
  if (!response.ok) throw new Error("Could not load account connections.");
  const data = await response.json();
  showAccounts(data.accounts);
}

async function updateAccount(provider, action) {
  const buttons = Array.from(accountCards.querySelectorAll("button:enabled"));
  buttons.forEach((button) => { button.disabled = true; });
  accountStatus.textContent = action === "connect" ? "Opening provider sign-in…" :
    (action === "refresh" ? "Refreshing the authorized records…" : "Clearing the local account connection…");
  try {
    const response = await fetch("/api/connections", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ provider, action })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not update the connection.");
    if (action === "connect") {
      location.assign(result.authorization_url);
      return;
    }
    showAccounts(result.accounts);
    accountStatus.textContent = action === "disconnect" ?
      "The local account connection and snapshot were cleared." : "Account snapshot refreshed.";
  } catch (error) {
    accountStatus.textContent = error.message;
    try {
      await loadAccounts();
    } catch {
      buttons.forEach((button) => { button.disabled = false; });
    }
  }
}

accountStatus.textContent = "Loading account connections…";
loadAccounts()
  .then(() => { accountStatus.textContent = ""; })
  .catch((error) => { accountStatus.textContent = error.name === "TimeoutError" ?
    "The dashboard did not respond. Restart GhostPrint and reload this page." : error.message; });
