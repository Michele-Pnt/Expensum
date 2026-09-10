const TALLY_SCRIPT_ID = "tally-embed-script";
const TALLY_SCRIPT_SRC = "https://tally.so/widgets/embed.js";

type TallyApi = {
  openPopup: (
    formId: string,
    options?: { hiddenFields?: Record<string, string>; hideTitle?: boolean },
  ) => void;
};

declare global {
  interface Window { Tally?: TallyApi }
}

let tallyLoadPromise: Promise<void> | null = null;

function loadTally(): Promise<void> {
  if (window.Tally) return Promise.resolve();
  if (tallyLoadPromise) return tallyLoadPromise;

  tallyLoadPromise = new Promise<void>((resolve, reject) => {
    const onLoad = () => window.Tally ? resolve() : reject(new Error("Tally API unavailable"));
    const onError = () => reject(new Error("Unable to load Tally"));
    const existing = document.getElementById(TALLY_SCRIPT_ID) as HTMLScriptElement | null;

    if (existing) {
      existing.addEventListener("load", onLoad, { once: true });
      existing.addEventListener("error", onError, { once: true });
      return;
    }

    const script = document.createElement("script");
    script.id = TALLY_SCRIPT_ID;
    script.src = TALLY_SCRIPT_SRC;
    script.async = true;
    script.addEventListener("load", onLoad, { once: true });
    script.addEventListener("error", onError, { once: true });
    document.head.appendChild(script);
  }).catch((error) => {
    tallyLoadPromise = null;
    throw error;
  });

  return tallyLoadPromise;
}

export async function openTallyWaitlist(formId: string, referralCode?: string | null): Promise<void> {
  await loadTally();
  window.Tally?.openPopup(formId, {
    hiddenFields: referralCode ? { ref: referralCode } : undefined,
    hideTitle: true,
  });
}
