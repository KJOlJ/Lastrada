let scheduled = false;

function acceptedResult(item) {
  const result = item.querySelector(".dtwResult");
  if (!result?.classList.contains("accepted")) return false;
  if (result.textContent !== "Supporting evidence") result.textContent = "Supporting evidence";
  result.setAttribute("aria-label", "Supporting stem comparison");
  return true;
}

export function keepAcceptedStemMatches(cell) {
  if (!cell) return { matched: 0, removed: 0 };

  const items = [...cell.querySelectorAll(".stemEvidenceItem")];
  if (!items.length) return { matched: 0, removed: 0 };

  cell.querySelector(".matchedStemEmptyState")?.remove();
  const lists = [...cell.querySelectorAll(".stemEvidenceList")];
  const primary =
    lists.find((list) => !list.closest(".moreStemEvidence")) || lists[0];
  const accepted = [];
  let removed = 0;

  for (const item of items) {
    if (acceptedResult(item)) accepted.push(item);
    else {
      item.remove();
      removed += 1;
    }
  }

  for (const item of accepted) {
    if (primary && item.parentElement !== primary) primary.append(item);
  }
  cell.querySelectorAll(".moreStemEvidence").forEach((details) => details.remove());

  if (!accepted.length) {
    cell.querySelectorAll(".stemEvidenceList").forEach((list) => list.remove());
    const state = document.createElement("span");
    state.className = "evidenceState matchedStemEmptyState";
    state.textContent = "No supporting stem match";
    const progress = cell.querySelector(".evidenceProgress");
    if (progress) progress.before(state);
    else cell.prepend(state);
  }

  cell.dataset.acceptedStemCount = String(accepted.length);
  return { matched: accepted.length, removed };
}

export function showAcceptedStemMatches(root = document) {
  root
    .querySelectorAll("[data-stem-dtw-evidence]")
    .forEach((cell) => keepAcceptedStemMatches(cell));
}

function scheduleAcceptedStemMatches() {
  if (scheduled || typeof window === "undefined") return;
  scheduled = true;
  window.requestAnimationFrame(() => {
    scheduled = false;
    showAcceptedStemMatches();
  });
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  const view = document.querySelector("#view");
  if (view) {
    new MutationObserver(scheduleAcceptedStemMatches).observe(view, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  }
  window.addEventListener("load", scheduleAcceptedStemMatches);
  scheduleAcceptedStemMatches();
}
