/**
 * Cart-abandonment recovery tracking snippet.
 *
 * This is the actual "plug and play" integration surface: any checkout page can
 * include this script and set a small config object.
 *
 * Usage on any site - identity comes from the merchant's own logged-in session,
 * the same way an analytics "identify" call works, never from a form the customer
 * fills in (they're already logged in, the merchant already has this):
 *   <script>
 *     window.RECOVERY_AGENT_CONFIG = {
 *       sessionId: "<your cart/session id>",
 *       cartValue: 1999.0,
 *       customerName: user.name,        // from the merchant's own session
 *       customerPhone: user.whatsapp,   // ditto - never a form field
 *       minTimeOnPageSeconds: 60,       // don't even consider abandonment before this
 *       inactivitySeconds: 900,         // idle time before a departure looks likely
 *       graceSeconds: 600,              // extra wait after that - cancels if they return
 *       endpoint: "/api/cart-abandoned",
 *       payButtonId: "pay-btn",
 *     };
 *   </script>
 *   <script src="/static/recovery-agent.js"></script>
 *
 * The numbers above are realistic production defaults (~15-25 min total before any
 * contact) - short enough not to lose the moment, long enough that briefly looking
 * away or reading a review on another tab doesn't get treated as abandonment. For a
 * live demo, override with small values via the config.
 *
 * Design: inactivity or the tab being hidden only starts a PENDING state, not an
 * immediate report - any real return (activity, or the tab becoming visible again)
 * within the grace window cancels it silently, no server call at all. Only a tab
 * actually closing is final (the page won't survive to reconsider), so that one
 * still reports right away. This is the "don't be pushy" half of the design - most
 * people who step away come back on their own, and they should never know the
 * system almost messaged them for it.
 */
(function () {
    const config = window.RECOVERY_AGENT_CONFIG || {};
    const minTimeOnPageMs = (config.minTimeOnPageSeconds ?? 60) * 1000;
    const inactivityMs = (config.inactivitySeconds ?? 900) * 1000;
    const graceMs = (config.graceSeconds ?? 600) * 1000;
    const endpoint = config.endpoint || "/api/cart-abandoned";

    const pageLoadedAt = Date.now();
    let fired = false;
    let paymentAttempted = false;
    let inactivityTimer = null;
    let graceTimer = null;
    let pending = false;

    function reportAbandonment(reason) {
        if (fired || paymentAttempted) return;
        fired = true;

        const payload = JSON.stringify({
            session_id: config.sessionId,
            abandonment_stage: config.abandonmentStage || "checkout_started",
        });

        if (navigator.sendBeacon) {
            navigator.sendBeacon(endpoint, new Blob([payload], { type: "application/json" }));
        } else {
            fetch(endpoint, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: payload,
                keepalive: true,
            });
        }
        console.log("[recovery-agent] abandonment confirmed and reported (" + reason + ")");
    }

    function cancelPending() {
        if (!pending) return;
        pending = false;
        if (graceTimer) clearTimeout(graceTimer);
        console.log("[recovery-agent] customer came back - pending abandonment cancelled, nothing sent");
    }

    function enterPending(reason) {
        if (fired || paymentAttempted || pending || Date.now() - pageLoadedAt < minTimeOnPageMs) return;
        pending = true;
        console.log("[recovery-agent] possible abandonment (" + reason + ") - waiting to see if they return");
        graceTimer = setTimeout(() => reportAbandonment(reason), graceMs);
    }

    function resetInactivityTimer() {
        cancelPending();
        if (inactivityTimer) clearTimeout(inactivityTimer);
        inactivityTimer = setTimeout(() => enterPending("inactivity"), inactivityMs);
    }

    ["mousemove", "keydown", "scroll", "input"].forEach((evt) =>
        document.addEventListener(evt, resetInactivityTimer, { passive: true })
    );
    resetInactivityTimer();

    // A closed tab is final - the page can't reconsider after this, so it reports
    // immediately rather than entering the cancellable pending state.
    window.addEventListener("beforeunload", () => reportAbandonment("tab_closed"));

    document.addEventListener("visibilitychange", () => {
        if (document.visibilityState === "hidden") {
            enterPending("tab_hidden");
        } else {
            cancelPending();
            resetInactivityTimer();
        }
    });

    const payBtn = document.getElementById(config.payButtonId || "pay-btn");
    if (payBtn) {
        payBtn.addEventListener("click", () => {
            paymentAttempted = true;
            if (inactivityTimer) clearTimeout(inactivityTimer);
            if (graceTimer) clearTimeout(graceTimer);
        });
    }
})();
