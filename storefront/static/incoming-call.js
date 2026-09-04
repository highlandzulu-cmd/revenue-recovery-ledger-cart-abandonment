/**
 * Shared "incoming call" UI controller - drives the _incoming_call.html
 * partial wherever it's included (checkout.html, phone.html).
 *
 * Synced across browser tabs via BroadcastChannel: a call triggered on one
 * page (checkout.html, from a real cart-abandonment decision) rings on every
 * other same-origin tab that has this loaded too - e.g. a standalone /phone
 * tab opened next to it for a demo recording. No server round trip, no
 * polling - same-origin tabs just talk to each other directly.
 */
(function () {
    const overlay = document.getElementById("incoming-call-overlay");
    if (!overlay) return; // partial isn't on this page

    const channel = "BroadcastChannel" in window ? new BroadcastChannel("recovery-agent-calls") : null;

    const avatar = document.getElementById("ios-call-avatar");
    const subEl = document.getElementById("ios-call-sub");
    const timerEl = document.getElementById("ios-call-timer");
    const acceptBtn = document.getElementById("ios-call-accept");
    const declineBtn = document.getElementById("ios-call-decline");
    const endBtn = document.getElementById("ios-call-end");
    const endGroup = document.getElementById("ios-call-end-group");
    const audio = document.getElementById("ios-call-audio");
    const clockEl = document.getElementById("ios-clock");
    let timerInterval = null;

    function updateClock() {
        const now = new Date();
        const h = now.getHours() % 12 || 12;
        const m = String(now.getMinutes()).padStart(2, "0");
        clockEl.textContent = h + ":" + m;
    }
    updateClock();
    setInterval(updateClock, 30000);

    function showIncomingCall() {
        avatar.classList.add("ringing");
        subEl.textContent = "mobile";
        subEl.hidden = false;
        timerEl.hidden = true;
        timerEl.textContent = "00:00";
        acceptBtn.parentElement.hidden = false;
        declineBtn.parentElement.hidden = false;
        endGroup.hidden = true;
        overlay.hidden = false;
    }

    function endCall() {
        audio.pause();
        audio.currentTime = 0;
        if (timerInterval) clearInterval(timerInterval);
        overlay.hidden = true;
    }

    acceptBtn.addEventListener("click", () => {
        avatar.classList.remove("ringing");
        subEl.hidden = true;
        acceptBtn.parentElement.hidden = true;
        declineBtn.parentElement.hidden = true;
        endGroup.hidden = false;
        timerEl.hidden = false;

        let seconds = 0;
        timerInterval = setInterval(() => {
            seconds++;
            const m = String(Math.floor(seconds / 60)).padStart(2, "0");
            const s = String(seconds % 60).padStart(2, "0");
            timerEl.textContent = m + ":" + s;
        }, 1000);

        audio.currentTime = 0;
        audio.play().catch(() => { /* no recording yet - call just stays quiet, same as a bad line */ });
        audio.onended = () => setTimeout(endCall, 1200);
    });

    declineBtn.addEventListener("click", endCall);
    endBtn.addEventListener("click", endCall);

    // Public API: rings this tab AND every other same-origin tab that has
    // this script loaded (via BroadcastChannel - includes itself only if it
    // also listens below, which it does, so calling this here is enough).
    window.triggerIncomingCall = function () {
        showIncomingCall();
        if (channel) channel.postMessage({ type: "incoming_call" });
    };

    if (channel) {
        channel.onmessage = (event) => {
            if (event.data && event.data.type === "incoming_call") showIncomingCall();
        };
    }

    const previewBtn = document.getElementById("preview-call-btn");
    if (previewBtn) previewBtn.addEventListener("click", window.triggerIncomingCall);
})();
