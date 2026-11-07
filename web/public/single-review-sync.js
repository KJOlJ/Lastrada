let scheduled = false;

function requestUrl(request) {
  if (typeof request === "string") return request;
  if (request instanceof URL) return request.href;
  return request?.url || "";
}

function refreshMountedDraft() {
  if (scheduled || !document.querySelector(".singleNatureReview")) return;
  scheduled = true;
  const view = document.querySelector("#view");
  const heading = view?.querySelector("h1");
  if (!view || !heading) {
    scheduled = false;
    return;
  }

  // The single-review state machine uses the previous screen heading as its
  // transition signal. Re-enter that transition after fresh result data arrives
  // so statistics, stems and prose are rebuilt from the new payload.
  view.style.visibility = "hidden";
  heading.textContent = "What did you use?";
  window.requestAnimationFrame(() =>
    window.requestAnimationFrame(() => {
      view.style.removeProperty("visibility");
      scheduled = false;
    }),
  );
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async (...arguments_) => {
    const response = await nativeFetch(...arguments_);
    try {
      const url = new URL(requestUrl(arguments_[0]), window.location.href);
      if (
        response.ok &&
        /\/api\/analyses\/[^/]+\/result(?:\?|$)/.test(url.pathname + url.search)
      ) {
        await response.clone().json().catch(() => null);
        window.setTimeout(refreshMountedDraft, 0);
      }
    } catch {}
    return response;
  };
}
